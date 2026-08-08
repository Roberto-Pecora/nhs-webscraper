"""Live integration tests for the Crawl4AI backend.

Marked ``integration`` and therefore excluded from the default CI unit
job. They require the ``crawl`` extra plus ``crawl4ai-setup`` (Playwright
Chromium) and make real network requests to My Planned Care.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("crawl4ai", reason="crawl extra not installed")

from nhs_scraper.backends.crawl4ai_backend import Crawl4AIBackend

TRUST_URL = "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/"


@pytest.mark.integration()
def test_scrape_live_trust_page_returns_parseable_html():
    backend = Crawl4AIBackend()
    page = asyncio.run(backend.scrape(TRUST_URL))

    assert page.url == TRUST_URL
    assert "Royal Berkshire" in page.html
    assert page.fetched_at.tzinfo is not None
