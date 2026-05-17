"""
Phase 2: The Scraper Module
Handles navigating to job boards and extracting job details using Playwright.
"""
from playwright.sync_api import sync_playwright
import urllib.parse

def scrape_linkedin(page, query, jobs):
    search_url = f"https://www.linkedin.com/jobs/search?keywords={urllib.parse.quote(query)}&location=Israel&f_AL=true"
    try:
        page.goto(search_url, timeout=15000)
        page.wait_for_selector(".base-card", timeout=5000)
        extracted_jobs = page.query_selector_all(".base-card")
        for job in extracted_jobs[:5]:
            title_element = job.query_selector(".base-search-card__title")
            company_element = job.query_selector(".base-search-card__subtitle")
            link_element = job.query_selector(".base-card__full-link")
            if title_element and company_element and link_element:
                jobs.append({
                    "title": title_element.inner_text().strip(),
                    "company": company_element.inner_text().strip(),
                    "description": f"LinkedIn Job. Details available at the link.",
                    "url": link_element.get_attribute("href")
                })
    except Exception as e:
        print(f"LinkedIn scraping yielded no results for '{query}' or timed out.")

def scrape_indeed(page, query, jobs):
    search_url = f"https://www.indeed.com/jobs?q={urllib.parse.quote(query)}&l=Israel"
    try:
        page.goto(search_url, timeout=15000)
        page.wait_for_selector(".job_seen_beacon", timeout=5000)
        extracted_jobs = page.query_selector_all(".job_seen_beacon")
        for job in extracted_jobs[:5]:
            title_element = job.query_selector("h2.jobTitle span")
            company_element = job.query_selector("span[data-testid='company-name']")
            link_element = job.query_selector("h2.jobTitle a")
            if title_element and company_element and link_element:
                link = link_element.get_attribute("href")
                if not link.startswith("http"):
                    link = "https://www.indeed.com" + link
                jobs.append({
                    "title": title_element.inner_text().strip(),
                    "company": company_element.inner_text().strip(),
                    "description": f"Indeed Job. Details available at the link.",
                    "url": link
                })
    except Exception as e:
        print(f"Indeed scraping yielded no results for '{query}' or timed out.")

def scrape_glassdoor(page, query, jobs):
    search_url = f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={urllib.parse.quote(query)}&locT=N&locId=119&locKeyword=Israel"
    try:
        page.goto(search_url, timeout=15000)
        page.wait_for_selector("[data-test='job-link']", timeout=5000)
        extracted_jobs = page.query_selector_all("li[data-test='jobListing']")
        for job in extracted_jobs[:5]:
            title_element = job.query_selector("[data-test='job-link']")
            company_element = job.query_selector("[data-test='employer-short-name']")
            if title_element and company_element:
                link = title_element.get_attribute("href")
                if not link.startswith("http"):
                    link = "https://www.glassdoor.com" + link
                jobs.append({
                    "title": title_element.inner_text().strip(),
                    "company": company_element.inner_text().strip(),
                    "description": f"Glassdoor Job. Details available at the link.",
                    "url": link
                })
    except Exception as e:
        print(f"Glassdoor scraping yielded no results for '{query}' or timed out.")

def scrape_wellfound(page, query, jobs):
    # Wellfound has strong anti-bot and requires specific URL structures
    # We will try a generic search approach
    search_url = f"https://wellfound.com/role/l/{query.replace(' ', '-').lower()}"
    try:
        page.goto(search_url, timeout=15000)
        # Wellfound's DOM changes often, try to look for job titles
        page.wait_for_selector("a[data-test='StartupResult']", timeout=5000)
        extracted_jobs = page.query_selector_all("a[data-test='StartupResult']")
        for job in extracted_jobs[:5]:
            title_element = job.query_selector("h2") # Rough approximation
            if title_element:
                link = job.get_attribute("href")
                if link and not link.startswith("http"):
                    link = "https://wellfound.com" + link
                jobs.append({
                    "title": title_element.inner_text().strip(),
                    "company": "Wellfound Startup", # Often hidden inside deeper divs
                    "description": f"Wellfound Job. Details available at the link.",
                    "url": link
                })
    except Exception as e:
        print(f"Wellfound scraping yielded no results for '{query}' or timed out.")

def scrape_jobs(search_queries: list = None):
    """
    Scrapes job listings for multiple queries across multiple job boards.
    """
    if search_queries is None:
        search_queries = [
            "Student Developer",
            "Python Student",
            "Software Engineer Student",
            "Data Engineer Junior", 
            "Junior Software Engineer", 
            "Junior Python Developer"
        ]
        
    jobs = []
    
    with sync_playwright() as p:
        # Run in headless mode for background execution
        browser = p.chromium.launch(headless=True)
        # Setup context with a user agent to help bypass simple bot protection
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        for query in search_queries:
            print(f"Scraping jobs for: {query}...")
            
            # Scrape LinkedIn
            scrape_linkedin(page, query, jobs)
            
            # Scrape Indeed
            scrape_indeed(page, query, jobs)
            
            # Scrape Glassdoor
            scrape_glassdoor(page, query, jobs)
            
            # Scrape Wellfound
            scrape_wellfound(page, query, jobs)
            
        print(f"Total scraping completed. Found {len(jobs)} total initial jobs.")
        context.close()
        browser.close()
        
    return jobs

if __name__ == "__main__":
    # Test the scraper independently
    scrape_jobs()
