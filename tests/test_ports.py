"""Contract tests for the CrawlBackend port.

A fake backend proves the protocol is satisfiable and lets the pipeline
be exercised end-to-end in later steps without a browser or network.
Coroutines are driven with ``asyncio.run`` to avoid a pytest-asyncio
dependency.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from nhs_scraper.domain import Page
from nhs_scraper.ports import CrawlBackend, CrawlOptions


class FakeBackend:
    """Minimal in-memory backend used across the test-suite."""

    def __init__(self, pages: dict[str, Page]):
        self._pages = pages

    async def scrape(self, url: str) -> Page:
        return self._pages[url]

    async def crawl(self, seed: str, options: CrawlOptions | None = None) -> list[Page]:
        return list(self._pages.values())


@pytest.fixture()
def page() -> Page:
    return Page(url="https://www.myplannedcare.nhs.uk/example/", html="<html></html>")


class TestCrawlBackendProtocol:
    def test_fake_backend_satisfies_protocol(self, page):
        assert isinstance(FakeBackend({page.url: page}), CrawlBackend)

    def test_non_conforming_object_rejected(self):
        assert not isinstance(object(), CrawlBackend)

    def test_port_methods_are_async(self):
        assert inspect.iscoroutinefunction(CrawlBackend.scrape)
        assert inspect.iscoroutinefunction(CrawlBackend.crawl)

    def test_fake_backend_scrape_round_trip(self, page):
        backend = FakeBackend({page.url: page})
        assert asyncio.run(backend.scrape(page.url)) is page

    def test_fake_backend_crawl_returns_all_pages(self, page):
        backend = FakeBackend({page.url: page})
        assert asyncio.run(backend.crawl(page.url)) == [page]


class TestCrawlOptions:
    def test_defaults(self):
        options = CrawlOptions()
        assert options.limit == 100
        assert options.max_depth == 2
        assert options.allow_subdomains is False
        assert options.concurrency == 8

    @pytest.mark.parametrize("limit", [0, -1])
    def test_invalid_limit_rejected(self, limit):
        with pytest.raises(ValueError, match="limit"):
            CrawlOptions(limit=limit)

    def test_negative_max_depth_rejected(self):
        with pytest.raises(ValueError, match="max_depth"):
            CrawlOptions(max_depth=-1)

    @pytest.mark.parametrize("concurrency", [0, -1])
    def test_invalid_concurrency_rejected(self, concurrency):
        with pytest.raises(ValueError, match="concurrency"):
            CrawlOptions(concurrency=concurrency)
