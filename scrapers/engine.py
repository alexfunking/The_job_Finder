"""
Scraping Engine v2.1 — Robust async parallel scraping with circuit breakers, metrics, caching, and evaluation logic.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
import logging
import os
import random
import threading
import time
import urllib.parse
import asyncio
from typing import Optional, Tuple, Dict, List, Any

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Route, Request
except ImportError:
    async_playwright = None
    Page = Browser = BrowserContext = Route = Request = Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_ERROR_DIR = os.path.join("scraper_errors")
os.makedirs(_ERROR_DIR, exist_ok=True)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORT_SIZES = [
    (1920, 1080), (1366, 768), (1280, 720), (1400, 900), (1600, 900), (1680, 1050),
]

_TRACKING_PARAMS = {
    "trackingId", "trk", "ref", "utm_source", "utm_medium", "utm_campaign", "utm_content", "source", "si", "currentJobId",
    "recommended_job", "lipi", "midToken", "rc", "vertical", "searchId", "utm_term", "utm_id", "utm_partner",
    "sc_upedinshare", "clickedTrackingId", "li_fat_id", "blurredFields", "refId", "ro", "sortBy", "f_TPR", "f_WT", "f_PP",
}

# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    if not url: return url
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for param in _TRACKING_PARAMS:
            qs.pop(param, None)
            for key in list(qs.keys()):
                if key.lower().startswith(param.lower()):
                    qs.pop(key, None)
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))
    except Exception:
        return url

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
class ScraperHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    CIRCUIT_OPEN = "circuit_open"

@dataclass
class SiteResult:
    site_name: str
    query: str
    jobs_found: int = 0
    success: bool = False
    response_time_ms: float = 0.0
    error: Optional[str] = None
    circuit_open: bool = False
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None: self.timestamp = datetime.now()

@dataclass
class ScraperMetrics:
    site_name: str
    total_requests: int = 0
    successful_requests: int = 0
    total_jobs_found: int = 0
    total_response_time: float = 0.0
    failures_in_a_row: int = 0
    last_success: Optional[datetime] = None
    last_fail_reason: Optional[str] = None

    @property
    def success_rate(self) -> float:
        return self.successful_requests / self.total_requests if self.total_requests > 0 else 1.0

    @property
    def avg_response_ms(self) -> float:
        return self.total_response_time / self.total_requests if self.total_requests > 0 else 0.0

    def record_success(self, jobs: int, elapsed_ms: float):
        self.total_requests += 1
        self.successful_requests += 1
        self.total_jobs_found += jobs
        self.total_response_time += elapsed_ms
        self.failures_in_a_row = 0
        self.last_success = datetime.now()

    def record_failure(self, reason: str = None):
        self.total_requests += 1
        self.failures_in_a_row += 1
        self.last_fail_reason = reason

    @property
    def health(self) -> ScraperHealth:
        if self.failures_in_a_row >= 15: return ScraperHealth.CIRCUIT_OPEN
        if self.failures_in_a_row >= 5: return ScraperHealth.FAILING
        if self.success_rate < 0.5: return ScraperHealth.DEGRADED
        return ScraperHealth.HEALTHY

# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------
class ScraperCache:
    def __init__(self, ttl_seconds: int = 3600, maxsize: int = 256):
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self._store: Dict[str, Tuple[float, List[dict]]] = {}
        self._lock = threading.Lock()

    def _key(self, site: str, query: str) -> str:
        return hashlib.md5(f"{site}:{query}".encode("utf-8")).hexdigest()

    def get(self, site: str, query: str) -> Optional[List[dict]]:
        key = self._key(site, query)
        with self._lock:
            if key in self._store:
                expiry, results = self._store[key]
                if time.time() < expiry: return results
                del self._store[key]
            return None

    def set(self, site: str, query: str, results: List[dict]):
        key = self._key(site, query)
        with self._lock:
            while len(self._store) >= self.maxsize:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (time.time() + self.ttl, results)

# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures: Dict[str, int] = defaultdict(int)
        self._last_failure: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, site_name: str) -> bool:
        with self._lock:
            if self._failures[site_name] >= self.failure_threshold:
                if time.time() - self._last_failure.get(site_name, 0) > self.recovery_timeout:
                    self._failures[site_name] = 0
                    return False
                return True
            return False

    def record_success(self, site_name: str):
        with self._lock:
            self._failures[site_name] = 0

    def record_failure(self, site_name: str):
        with self._lock:
            self._failures[site_name] += 1
            self._last_failure[site_name] = time.time()

# ---------------------------------------------------------------------------
# Anti-bot helpers
# ---------------------------------------------------------------------------
def _get_random_headers() -> Dict[str, str]:
    return {
        "Accept-Language": random.choice(["en-US,en;q=0.9,he;q=0.8", "en-GB,en;q=0.9,he;q=0.8", "en-US,en;q=0.9"]),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Not.A/Brand";v="8", "Chromium";v="124"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": random.choice(["Windows", "macOS", "Linux"]),
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }

def _get_browser_args() -> List[str]:
    return [
        "--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox",
        "--js-flags=--max-old-space-size=384", "--disable-blink-features=AutomationControlled",
        "--disable-extensions", "--disable-plugins", "--disable-images",
        "--disable-background-networking", "--no-first-run", "--disable-default-apps",
        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
        "--force-webrtc-ip-handling-policy=default_public_interface_only", "--web-security=false",
    ]

class ResourceBlocker:
    TRACKER_PATTERNS = ["google-analytics", "doubleclick", "facebook.net", "hotjar", "amplitude", "segment", "googleadservices", "googlesyndication", "analytics", "beacon", "track", "pixel"]
    BLOCKED_TYPES = {"image", "media", "font", "imageset", "webp", "stylesheet"}

    async def handle_route(self, route: Route, request: Request):
        rt = request.resource_type
        url = request.url.lower()
        if rt in self.BLOCKED_TYPES or any(t in url for t in self.TRACKER_PATTERNS):
            await route.abort()
        elif rt in {"xhr", "fetch", "script"} and any(p in url for p in self.TRACKER_PATTERNS):
            await route.abort()
        else:
            await route.continue_()

# ---------------------------------------------------------------------------
# Scrolling helper
# ---------------------------------------------------------------------------
async def auto_scroll(page: Page, max_attempts: int = 10, pause: float = 0.5):
    for i in range(max_attempts):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause + random.uniform(0.0, 0.3))

# ---------------------------------------------------------------------------
# Base Scraper
# ---------------------------------------------------------------------------
class BaseScraper:
    def __init__(self, name: str, base_url: str = ""):
        self.name = name
        self.base_url = base_url

    def build_url(self, query: str) -> str:
        raise NotImplementedError

    async def extract(self, page: Page, query: str) -> List[dict]:
        url = self.build_url(query)
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector("body", timeout=5000)
        except:
            pass
        await asyncio.sleep(0.5 + random.uniform(0.0, 0.5))
        await self.wait_for_content(page)
        await auto_scroll(page, max_attempts=8, pause=0.4)
        jobs = await self.parse_via_evaluate(page)
        
        valid_jobs = []
        for job in jobs[:40]:
            if job.get("title"):
                link = job.get("url")
                if link and not link.startswith("http"):
                    job["url"] = self.base_url + link
                job["url"] = normalize_url(job.get("url"))
                job["description"] = f"{self.name.capitalize()} Job: {job.get('title')} @ {job.get('company', 'Unknown')}"
                valid_jobs.append(job)
        return valid_jobs

    async def wait_for_content(self, page: Page):
        pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return []

# ---------------------------------------------------------------------------
# Site Scraper Definitions
# ---------------------------------------------------------------------------
class LinkedInScraper(BaseScraper):
    def __init__(self): super().__init__("linkedin", "https://www.linkedin.com")
    def build_url(self, query: str) -> str:
        return f"https://www.linkedin.com/jobs/search?keywords={urllib.parse.quote(query)}&location=Israel&f_AL=true"
    
    async def wait_for_content(self, page: Page):
        try: await page.wait_for_selector(".base-card, li[data-view-name='jobs-frontend']", timeout=7000)
        except: pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return await page.evaluate("""() => {
            let res = [];
            document.querySelectorAll(".base-card, li[data-view-name='jobs-frontend'], .jobs-search-results__list-item").forEach(c => {
                let title = c.querySelector(".base-search-card__title, .job-search-card__title, h3 a, .base-card__title");
                let comp = c.querySelector(".base-search-card__subtitle, .job-card__company-name, .base-card__subtitle");
                let link = c.querySelector(".base-card__full-link, .job-search-card__title-link, h3 a");
                let loc = c.querySelector(".job-search-card__location, .base-search-card__metadata span:last-child");
                if (title && (link || title)) {
                    res.push({
                        title: title.innerText.trim(),
                        company: comp ? comp.innerText.trim() : "Unknown",
                        url: link ? link.getAttribute("href") : "",
                        location: loc ? loc.innerText.trim() : "Israel"
                    });
                }
            });
            return res;
        }""")

class IndeedScraper(BaseScraper):
    def __init__(self): super().__init__("indeed", "https://www.indeed.com")
    def build_url(self, query: str) -> str:
        return f"https://www.indeed.com/jobs?q={urllib.parse.quote(query)}&l=Israel"

    async def wait_for_content(self, page: Page):
        try: await page.wait_for_selector(".job_seen_beacon, [data-testid='jobTitle-link']", timeout=7000)
        except: pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return await page.evaluate("""() => {
            let res = [];
            document.querySelectorAll(".job_seen_beacon, .jobsearch-ResultsList > li").forEach(c => {
                let title = c.querySelector("h2.jobTitle span, [data-testid='jobTitle-link'], h2 a span");
                let comp = c.querySelector("[data-testid='company-name'], .companyName, span.company");
                let link = c.querySelector("h2.jobTitle a, [data-testid='jobTitle-link'] a, h2 a");
                let loc = c.querySelector("[data-testid='text-location'], .companyLocation");
                if (title) {
                    res.push({
                        title: title.innerText.trim(),
                        company: comp ? comp.innerText.trim() : "Unknown",
                        url: link ? link.getAttribute("href") : "",
                        location: loc ? loc.innerText.trim() : "Israel"
                    });
                }
            });
            return res;
        }""")

class JobMasterScraper(BaseScraper):
    def __init__(self): super().__init__("jobmaster", "https://www.jobmaster.co.il")
    def build_url(self, query: str) -> str:
        return f"https://www.jobmaster.co.il/jobs/?q={urllib.parse.quote(query)}"

    async def wait_for_content(self, page: Page):
        try: await page.wait_for_selector(".JobItem, .job-item", timeout=7000)
        except: pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return await page.evaluate("""() => {
            let res = [];
            document.querySelectorAll(".JobItem, .job-item, [data-job-id]").forEach(c => {
                let title = c.querySelector("[data-testid='job-content-list'] > a, .CardHeader");
                if (!title) {
                    let a = c.querySelector("a");
                    if (a && a.innerText.trim() && a.getAttribute("href")) title = a;
                }
                let comp = c.querySelector(".CardHeader + div, .companyNameLink, .company-name");
                let link = c.querySelector(".CardHeader a, a[href*='jobs/']");
                let loc = c.querySelector(".jobLocation, .JobItemCity, .location");
                if (title) {
                    res.push({
                        title: title.innerText.trim(),
                        company: comp ? comp.innerText.trim() : "Unknown",
                        url: link ? link.getAttribute("href") : "",
                        location: loc ? loc.innerText.trim() : "Israel"
                    });
                }
            });
            return res;
        }""")

class DrushimScraper(BaseScraper):
    def __init__(self): super().__init__("drushim", "https://www.drushim.co.il")
    def build_url(self, query: str) -> str:
        return f"https://www.drushim.co.il/jobs/search/{urllib.parse.quote(query)}/"

    async def wait_for_content(self, page: Page):
        try: await page.wait_for_selector(".job-item-main", timeout=7000)
        except: pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return await page.evaluate("""() => {
            let res = [];
            document.querySelectorAll(".job-item-main").forEach(c => {
                let title = c.querySelector(".job-url, .job-title, h3 a, h2 a");
                let comp = c.querySelector(".company-name, .company");
                let link = c.querySelector(".job-url, .job-title a, h3 a");
                let loc = c.querySelector(".job-location, .location, .city");
                if (title) {
                    res.push({
                        title: title.innerText.trim(),
                        company: comp ? comp.innerText.trim() : "Unknown",
                        url: link ? link.getAttribute("href") : "",
                        location: loc ? loc.innerText.trim() : "Israel"
                    });
                }
            });
            return res;
        }""")

class AllJobsScraper(BaseScraper):
    def __init__(self): super().__init__("alljobs", "https://www.alljobs.co.il")
    def build_url(self, query: str) -> str:
        return f"https://www.alljobs.co.il/SearchResults.aspx?position={urllib.parse.quote(query)}&type=0&city=0"

    async def wait_for_content(self, page: Page):
        try: await page.wait_for_selector(".job-content, .job-item", timeout=8000)
        except: pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return await page.evaluate("""() => {
            let res = [];
            document.querySelectorAll(".job-content, .job-item").forEach(c => {
                let title = c.querySelector(".job-content-title a, .job-title a, h2 a, .title a, a[data-testid='job-link']");
                let comp = c.querySelector(".job-content-company, .company-name, .company");
                let link = c.querySelector(".job-content-title a, .job-title a, h2 a");
                let loc = c.querySelector(".job-content-location, .location, .city");
                if (title) {
                    res.push({
                        title: title.innerText.trim(),
                        company: comp ? comp.innerText.trim() : "Unknown",
                        url: link ? link.getAttribute("href") : "",
                        location: loc ? loc.innerText.trim() : "Israel"
                    });
                }
            });
            return res;
        }""")

class NishaScraper(BaseScraper):
    def __init__(self): super().__init__("nisha", "https://www.nisha.co.il")
    def build_url(self, query: str) -> str:
        return f"https://www.nisha.co.il/jobs/?s={urllib.parse.quote(query)}"

    async def wait_for_content(self, page: Page):
        try: await page.wait_for_selector(".job-listing, .job_listing, article.job", timeout=8000)
        except: pass

    async def parse_via_evaluate(self, page: Page) -> List[dict]:
        return await page.evaluate("""() => {
            let res = [];
            document.querySelectorAll(".job-listing, .job_listing, .job-item, article.job").forEach(c => {
                let title = c.querySelector("h3 a, h2 a, .job-title a, a.job-link");
                let comp = c.querySelector(".company, .employer, .company-name");
                let link = c.querySelector("h3 a, h2 a, .job-title a");
                let loc = c.querySelector(".location, .city, .job-location");
                if (title) {
                    res.push({
                        title: title.innerText.trim(),
                        company: comp ? comp.innerText.trim() : "Unknown",
                        url: link ? link.getAttribute("href") : "",
                        location: loc ? loc.innerText.trim() : "Israel"
                    });
                }
            });
            return res;
        }""")

# ---------------------------------------------------------------------------
# Scraping Engine
# ---------------------------------------------------------------------------
class ScrapingEngine:
    def __init__(self, max_concurrent: int = 6, cache_ttl: int = 3600,
                 enable_caching: bool = True, cb_failure_threshold: int = 5):
        self.max_concurrent = max_concurrent
        self.cache = ScraperCache(ttl_seconds=cache_ttl) if enable_caching else None
        self.circuit_breaker = CircuitBreaker(failure_threshold=cb_failure_threshold)
        self.metrics: Dict[str, ScraperMetrics] = {}
        self.resource_blocker = ResourceBlocker()
        self._metrics_lock = threading.Lock()
        self._all_jobs_result: List[dict] = []
        self._jobs_lock = threading.Lock()
        self.semaphore = asyncio.Semaphore(max_concurrent)

    def _get_metric(self, site_name: str) -> ScraperMetrics:
        with self._metrics_lock:
            if site_name not in self.metrics:
                self.metrics[site_name] = ScraperMetrics(site_name=site_name)
            return self.metrics[site_name]

    async def _scrape_site(self, scraper: BaseScraper, query: str, browser: Browser) -> SiteResult:
        site_name = scraper.name
        if self.circuit_breaker.is_open(site_name):
            return SiteResult(site_name=site_name, query=query, success=False, circuit_open=True, error="Circuit breaker open")

        if self.cache:
            cached = self.cache.get(site_name, query)
            if cached is not None:
                with self._jobs_lock: self._all_jobs_result.extend(cached)
                return SiteResult(site_name=site_name, query=query, success=True, jobs_found=len(cached), error="cache_hit")

        async with self.semaphore:
            start = time.perf_counter()
            jobs = []
            error = None
            context = None
            try:
                width, height = random.choice(_VIEWPORT_SIZES)
                context = await browser.new_context(
                    user_agent=random.choice(_USER_AGENTS),
                    accept_downloads=False,
                    java_script_enabled=True,
                    viewport={"width": width, "height": height},
                    locale="en-US",
                    timezone_id="Asia/Jerusalem",
                    extra_http_headers=_get_random_headers()
                )
                
                page = await context.new_page()
                page.set_default_timeout(12000)
                page.set_default_navigation_timeout(18000)
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    window.chrome = { runtime: {} };
                    window.navigator.languages = ['en-US', 'en', 'he'];
                """)
                await page.route("**/*", self.resource_blocker.handle_route)

                try:
                    jobs = await scraper.extract(page, query)
                    if self.cache: self.cache.set(site_name, query, jobs)
                    self.circuit_breaker.record_success(site_name)
                except Exception as e:
                    error = f"{type(e).__name__}: {str(e)[:120]}"
                    logger.error(f"[{site_name}] Query '{query}' failed: {error}")
                    self.circuit_breaker.record_failure(site_name)
            except Exception as e:
                error = f"Context error: {type(e).__name__}: {str(e)[:120]}"
                logger.error(f"[{site_name}] Browser context failed: {error}")
                self.circuit_breaker.record_failure(site_name)
            finally:
                if context: await context.close()

            elapsed_ms = (time.perf_counter() - start) * 1000
            metric = self._get_metric(site_name)

            if error:
                metric.record_failure(error)
                return SiteResult(site_name=site_name, query=query, success=False, jobs_found=0, response_time_ms=elapsed_ms, error=error)
            else:
                metric.record_success(len(jobs), elapsed_ms)
                with self._jobs_lock: self._all_jobs_result.extend(jobs)
                return SiteResult(site_name=site_name, query=query, success=True, jobs_found=len(jobs), response_time_ms=elapsed_ms)

    async def run_async(self, scrapers: List[BaseScraper], queries: List[str]) -> Tuple[List[dict], List[SiteResult]]:
        self._all_jobs_result = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=_get_browser_args())
            try:
                tasks = []
                for scraper in scrapers:
                    for query in queries:
                        tasks.append(self._scrape_site(scraper, query, browser))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                final_results = []
                for r in results:
                    if isinstance(r, Exception):
                        final_results.append(SiteResult("Unknown", "Unknown", error=str(r)))
                    else:
                        final_results.append(r)
                return self._all_jobs_result, final_results
            finally:
                await browser.close()

    def get_health_report(self) -> Dict[str, Any]:
        report = {}
        for name, metric in self.metrics.items():
            report[name] = {
                "health": metric.health.value,
                "success_rate": round(metric.success_rate * 100, 1),
                "avg_response_ms": round(metric.avg_response_ms, 1),
                "total_requests": metric.total_requests,
                "jobs_found": metric.total_jobs_found,
            }
        return report

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def run_scrape_jobs(search_queries: Optional[List[str]] = None, max_workers: int = 6) -> List[dict]:
    if search_queries is None:
        search_queries = [
            "Student Developer", "Python Student", "Software Engineer Student",
            "Data Engineer Junior", "Junior Software Engineer", "Junior Python Developer",
            "Junior Data Analyst", "בוגר מדעי המחשב", "משרת סטודנט",
        ]

    logger.info(f"Starting Async Scraping Engine with {len(search_queries)} queries (max_concurrent={max_workers})")
    engine = ScrapingEngine(max_concurrent=max_workers, cache_ttl=3600, enable_caching=True, cb_failure_threshold=5)
    
    scrapers = [
        LinkedInScraper(),
        IndeedScraper(),
        JobMasterScraper(),
        DrushimScraper(),
        AllJobsScraper(),
        NishaScraper(),
    ]

    try:
        # Avoid "Event loop is already running" issues
        try:
            loop = asyncio.get_running_loop()
            jobs, results = loop.run_until_complete(engine.run_async(scrapers, search_queries))
        except RuntimeError:
            jobs, results = asyncio.run(engine.run_async(scrapers, search_queries))
    except Exception as e:
        logger.error(f"Critical error in scraping: {e}")
        return []

    success_count = sum(1 for r in results if getattr(r, 'success', False))
    total_jobs = sum(getattr(r, 'jobs_found', 0) for r in results)
    logger.info(f"Scraping complete: {success_count}/{len(results)} tasks succeeded, {total_jobs} jobs found")

    return jobs

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run_scrape_jobs(["Junior Python Developer"])
    for job in results[:5]:
        print(job.get("title"), "@", job.get("company"), "-", job.get("url"))
