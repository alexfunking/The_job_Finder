"""
Scraper Health Monitor
Tracks and reports the health of individual job board scrapers based on the V2 engine.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scrapers.engine import ScrapingEngine, CircuitBreaker

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def print_health_report():
    """Print a health report and test the circuit breaker."""
    print("\n" + "=" * 70)
    print(" SCRAPER HEALTH REPORT & CIRCUIT BREAKER TEST")
    print("=" * 70)

    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=1800)
    
    cb.record_failure("linkedin")
    cb.record_failure("linkedin")
    cb.record_failure("linkedin")
    cb.record_failure("indeed")

    print(f"\nlinkedin failures: 3, circuit open: {cb.is_open('linkedin')}")
    print(f"indeed failures: 1, circuit open: {cb.is_open('indeed')}")

    cb.record_success("linkedin")
    print(f"linkedin after success, circuit open: {cb.is_open('linkedin')}")

    # Simulate max failures
    for _ in range(5):
        cb.record_failure("indeed")
    print(f"indeed after 5 failures, circuit open: {cb.is_open('indeed')}")

    print("\n" + "=" * 70)
    print(" Report complete")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    print_health_report()
