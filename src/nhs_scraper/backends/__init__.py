"""Crawl backend adapters.

Importing this package is safe without optional dependencies installed:
each backend module handles its own missing-dependency fallback and only
raises when the backend is actually constructed.
"""

from nhs_scraper.backends.crawl4ai_backend import Crawl4AIBackend, CrawlError

__all__ = ["Crawl4AIBackend", "CrawlError"]
