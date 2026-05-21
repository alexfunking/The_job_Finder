"""
Test suite for the scraper module.
Tests cover parallel scraping, circuit breakers, URL normalization, and smoke tests.
"""
import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scrapers import scraper
from db import database


class TestUrlNormalization(unittest.TestCase):
    def test_strips_tracking_params(self):
        url = "https://www.linkedin.com/jobs/view/123?trk=abc&ref=def&utm_source=email"
        result = scraper.normalize_url(url)
        self.assertNotIn("trk=", result)
        self.assertNotIn("ref=", result)
        self.assertNotIn("utm_source=", result)
        self.assertIn("linkedin.com", result)

    def test_handles_empty_url(self):
        self.assertEqual(scraper.normalize_url(""), "")

    def test_leaves_clean_urls_alone(self):
        url = "https://www.example.com/jobs/123"
        self.assertEqual(scraper.normalize_url(url), url)


class TestCircuitBreaker(unittest.TestCase):
    def test_initially_closed(self):
        cb = scraper._CircuitBreaker(failure_threshold=3)
        self.assertFalse(cb.is_open("linkedin"))

    def test_opens_after_failures(self):
        cb = scraper._CircuitBreaker(failure_threshold=2)
        cb.record_failure("linkedin")
        cb.record_failure("linkedin")
        self.assertTrue(cb.is_open("linkedin"))

    def test_resets_after_success(self):
        cb = scraper._CircuitBreaker(failure_threshold=2)
        cb.record_failure("linkedin")
        cb.record_success("linkedin")
        self.assertFalse(cb.is_open("linkedin"))

    def test_cooldown_resets(self):
        import time
        cb = scraper._CircuitBreaker(failure_threshold=1, cooldown_seconds=2)
        cb.record_failure("linkedin")
        self.assertTrue(cb.is_open("linkedin"))
        time.sleep(0.1)
        # Should still be open since cooldown hasn't elapsed
        self.assertTrue(cb.is_open("linkedin"))
        time.sleep(2.1)
        # After cooldown should be reset
        self.assertFalse(cb.is_open("linkedin"))


class TestScraperConfig(unittest.TestCase):
    def test_default_queries_present(self):
        self.assertTrue(len(scraper.DEFAULT_QUERIES) > 0)
        self.assertIn("Junior Python Developer", scraper.DEFAULT_QUERIES)

    def test_scraper_sites_defined(self):
        self.assertTrue(len(scraper.SCRAPER_SITES) > 0)
        enabled = [s for s in scraper.SCRAPER_SITES if s[2]]
        self.assertTrue(len(enabled) > 0)


class TestSmokeScrapeJobs(unittest.TestCase):
    """Smoke test — run the scraper with a minimal set of queries."""

    @patch("scrapers.scraper.sync_playwright")
    def test_scrape_jobs_returns_list(self, mock_playwright):
        """Mock out Playwright and verify scrape_jobs returns a list."""
        mock_browser = Mock()
        mock_context = Mock()
        mock_page = Mock()

        # Set up the mock chain
        mock_playwright.return_value.__enter__ = Mock(return_value=mock_playwright.return_value)
        mock_playwright.return_value.__exit__ = Mock(return_value=None)
        mock_playwright.return_value.chromium = Mock()
        mock_playwright.return_value.chromium.launch = Mock(return_value=mock_browser)

        # Browser is used in the context
        mock_browser.new_context = Mock(return_value=mock_context)
        mock_context.new_page = Mock(return_value=mock_page)

        # Each scraper adds to jobs list but with mocked page we only check it doesn't crash
        mock_page.goto = Mock(return_value=None)
        mock_page.query_selector = Mock(return_value=Mock(get_attribute=Mock(return_value="https://test.com")))
        mock_page.query_selector_all = Mock(return_value=[])

        # Run with minimal queries
        results = scraper.scrape_jobs(["Junior Python Developer"])
        self.assertIsInstance(results, list)


class TestDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        # Use an in-memory database for testing
        import sqlite3
        self.test_db_path = "test_jobs.db"
        # Save original and override
        self.orig_db = database.DB_NAME
        database.DB_NAME = self.test_db_path

    def tearDown(self):
        # Restore and cleanup
        database.DB_NAME = self.orig_db
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_url_normalization_matches_scraper(self):
        """Verify DB normalization uses same logic as scraper."""
        url1 = "https://www.linkedin.com/jobs/view/123?trk=abc&ref=def"
        url2 = "https://www.linkedin.com/jobs/view/123?ref=def&trk=abc"
        self.assertEqual(
            scraper.normalize_url(url1),
            scraper.normalize_url(url2)
        )

    def test_deduplication_with_scraper_urls(self):
        """Make sure scraper URLs survive dedup in DB."""
        database.init_db()
        database.add_job(
            title="Junior Python Dev",
            company="TestCo",
            url="https://example.com/job/1",
            location="Tel Aviv",
            ai_summary='{"match_score": 90}',
            stage="To Apply"
        )
        database.add_job(
            title="Junior Python Dev",
            company="TestCo",
            url="https://example.com/job/1?trk=abc",
            location="Tel Aviv",
            ai_summary='{"match_score": 85}',
            stage="To Apply"
        )
        # After normalization, second should be duplicate
        self.assertTrue(database.is_job_processed("https://example.com/job/1"))


class TestEmailTracker(unittest.TestCase):
    def test_detect_provider_gmail(self):
        from scrapers.email_tracker import _detect_provider
        name, config = _detect_provider("user@gmail.com")
        self.assertEqual(name, "gmail")
        self.assertEqual(config["host"], "imap.gmail.com")

    def test_detect_provider_outlook(self):
        from scrapers.email_tracker import _detect_provider
        name, config = _detect_provider("user@outlook.com")
        self.assertEqual(name, "outlook")
        self.assertEqual(config["host"], "outlook.office365.com")


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


if __name__ == "__main__":
    run_tests()
