"""
Test suite for the scraper module (V2 Engine).
Tests cover engine components, parallel scraping, circuit breakers, URL normalization, cache, and database integration.
"""
import sys
import os
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scrapers import engine
from db import database


class TestUrlNormalization(unittest.TestCase):
    def test_strips_tracking_params(self):
        url = "https://www.linkedin.com/jobs/view/123?trk=abc&ref=def&utm_source=email"
        result = engine.normalize_url(url)
        self.assertNotIn("trk=", result)
        self.assertNotIn("ref=", result)
        self.assertNotIn("utm_source=", result)
        self.assertIn("linkedin.com", result)

    def test_handles_empty_url(self):
        self.assertEqual(engine.normalize_url(""), "")

    def test_leaves_clean_urls_alone(self):
        url = "https://www.example.com/jobs/123"
        self.assertEqual(engine.normalize_url(url), url)


class TestCircuitBreaker(unittest.TestCase):
    def test_initially_closed(self):
        cb = engine.CircuitBreaker(failure_threshold=3)
        self.assertFalse(cb.is_open("linkedin"))

    def test_opens_after_failures(self):
        cb = engine.CircuitBreaker(failure_threshold=2)
        cb.record_failure("linkedin")
        cb.record_failure("linkedin")
        self.assertTrue(cb.is_open("linkedin"))

    def test_resets_after_success(self):
        cb = engine.CircuitBreaker(failure_threshold=2)
        cb.record_failure("linkedin")
        cb.record_failure("linkedin")
        cb.record_success("linkedin")
        self.assertFalse(cb.is_open("linkedin"))

    def test_recovery_timeout_resets(self):
        import time
        cb = engine.CircuitBreaker(failure_threshold=1, recovery_timeout=1)
        cb.record_failure("linkedin")
        self.assertTrue(cb.is_open("linkedin"))
        time.sleep(1.1)
        self.assertFalse(cb.is_open("linkedin"))


class TestScraperCache(unittest.TestCase):
    def test_cache_get_set(self):
        cache = engine.ScraperCache(ttl_seconds=60)
        test_jobs = [{"title": "Dev", "url": "https://example.com/1"}]
        cache.set("linkedin", "python", test_jobs)
        retrieved = cache.get("linkedin", "python")
        self.assertEqual(retrieved, test_jobs)

    def test_cache_miss(self):
        cache = engine.ScraperCache(ttl_seconds=60)
        self.assertIsNone(cache.get("linkedin", "nonexistent"))


class TestDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(os.path.dirname(__file__), "test_jobs.db")
        self.orig_db = database.DB_NAME
        database.DB_NAME = self.test_db_path

    def tearDown(self):
        database.DB_NAME = self.orig_db
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_url_normalization_matches_scraper(self):
        url1 = "https://www.linkedin.com/jobs/view/123?trk=abc&ref=def"
        url2 = "https://www.linkedin.com/jobs/view/123?ref=def&trk=abc"
        self.assertEqual(
            engine.normalize_url(url1),
            engine.normalize_url(url2)
        )

    def test_deduplication_with_scraper_urls(self):
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
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(sys.modules[__name__]))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


if __name__ == "__main__":
    run_tests()
