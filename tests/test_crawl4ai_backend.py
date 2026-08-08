"""Unit tests for the Crawl4AI backend — fully offline, no browser.

crawl4ai itself is not required: the module's lazily-imported attributes
are monkeypatched with stubs, and ``FakeCrawler`` (an async context
manager) stands in for ``AsyncWebCrawler``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import nhs_scraper.backends.crawl4ai_backend as backend_module
from nhs_scraper.backends.crawl4ai_backend import Crawl4AIBackend, CrawlError
from nhs_scraper.ports import CrawlBackend, CrawlOptions


class FakeCrawler:
    """Stands in for AsyncWebCrawler; returns canned results from arun."""

    def __init__(self, results):
        self._results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url, config=None):
        return self._results


def make_result(**overrides):
    base = dict(
        url="https://www.myplannedcare.nhs.uk/example/",
        html="<html>raw</html>",
        cleaned_html="<html>clean</html>",
        markdown="# Title",
        metadata={"title": "Example"},
        success=True,
        error_message=None,
    )
    return SimpleNamespace(**{**base, **overrides})


@pytest.fixture()
def stubbed_crawl4ai(monkeypatch):
    """Replace the lazily-imported crawl4ai symbols with kwarg-capturing stubs."""
    captured: dict = {}

    class StubRunConfig:
        def __init__(self, **kwargs):
            captured["config_kwargs"] = kwargs

    class StubBFS:
        def __init__(self, **kwargs):
            captured["strategy_kwargs"] = kwargs

    monkeypatch.setattr(backend_module, "CrawlerRunConfig", StubRunConfig)
    monkeypatch.setattr(backend_module, "BFSDeepCrawlStrategy", StubBFS)
    return captured


class TestProtocolConformance:
    def test_satisfies_crawl_backend_port(self):
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(make_result()))
        assert isinstance(backend, CrawlBackend)

    def test_missing_dependency_raises_runtime_error(self, monkeypatch):
        monkeypatch.setattr(backend_module, "AsyncWebCrawler", None)
        with pytest.raises(RuntimeError, match="crawl4ai is not installed"):
            Crawl4AIBackend()


class TestScrape:
    def test_returns_domain_page(self, stubbed_crawl4ai):
        result = make_result()
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(result))
        page = asyncio.run(backend.scrape(result.url))

        assert page.url == result.url
        assert page.html == "<html>clean</html>"  # cleaned_html preferred
        assert page.markdown == "# Title"
        assert page.metadata["title"] == "Example"
        assert page.fetched_at.tzinfo is not None

    def test_falls_back_to_raw_html(self, stubbed_crawl4ai):
        result = make_result(cleaned_html=None)
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(result))
        page = asyncio.run(backend.scrape(result.url))

        assert page.html == "<html>raw</html>"

    def test_unwraps_markdown_generation_result(self, stubbed_crawl4ai):
        result = make_result(markdown=SimpleNamespace(raw_markdown="# Raw"))
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(result))
        page = asyncio.run(backend.scrape(result.url))

        assert page.markdown == "# Raw"

    def test_unsuccessful_result_raises_crawl_error(self, stubbed_crawl4ai):
        result = make_result(success=False, error_message="timeout")
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(result))

        with pytest.raises(CrawlError, match="timeout"):
            asyncio.run(backend.scrape(result.url))


class TestCrawl:
    def test_maps_options_to_deep_crawl_strategy(self, stubbed_crawl4ai):
        results = [
            make_result(url="https://www.myplannedcare.nhs.uk/a/"),
            make_result(url="https://www.myplannedcare.nhs.uk/b/"),
        ]
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(results))
        pages = asyncio.run(
            backend.crawl(
                "https://www.myplannedcare.nhs.uk/",
                CrawlOptions(limit=25, max_depth=3),
            )
        )

        assert [p.url for p in pages] == [r.url for r in results]
        assert stubbed_crawl4ai["strategy_kwargs"] == {"max_depth": 3, "max_pages": 25}

    def test_default_options_when_none(self, stubbed_crawl4ai):
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler([make_result()]))
        asyncio.run(backend.crawl("https://www.myplannedcare.nhs.uk/"))

        assert stubbed_crawl4ai["strategy_kwargs"] == {"max_depth": 2, "max_pages": 100}

    def test_unsuccessful_results_are_skipped(self, stubbed_crawl4ai):
        results = [
            make_result(url="https://www.myplannedcare.nhs.uk/a/"),
            make_result(success=False, error_message="boom"),
            make_result(url="https://www.myplannedcare.nhs.uk/c/"),
        ]
        backend = Crawl4AIBackend(crawler_factory=lambda: FakeCrawler(results))
        pages = asyncio.run(backend.crawl("https://www.myplannedcare.nhs.uk/"))

        assert [p.url for p in pages] == [
            "https://www.myplannedcare.nhs.uk/a/",
            "https://www.myplannedcare.nhs.uk/c/",
        ]
