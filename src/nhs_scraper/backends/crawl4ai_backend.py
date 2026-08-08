"""Crawl4AI backend: adapts ``AsyncWebCrawler`` to the ``CrawlBackend`` port.

crawl4ai is an optional dependency (install the ``crawl`` extra). It is
imported with a graceful fallback so the rest of the package — and the
whole unit-test suite — works without it; unit tests monkeypatch the
module attributes and inject a fake crawler, so no browser is required
offline. Constructing the backend without crawl4ai (and without an
injected factory) raises ``RuntimeError`` with the remedy.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from nhs_scraper.domain import Page
from nhs_scraper.ports import CrawlOptions

try:  # pragma: no cover - the real import is exercised by integration tests
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
except ImportError:  # pragma: no cover
    AsyncWebCrawler = None  # type: ignore[assignment]
    CrawlerRunConfig = None  # type: ignore[assignment]
    BFSDeepCrawlStrategy = None  # type: ignore[assignment]


class CrawlError(RuntimeError):
    """Raised when Crawl4AI reports an unsuccessful scrape."""


class Crawl4AIBackend:
    """``CrawlBackend`` implementation backed by Crawl4AI.

    ``crawler_factory`` may be injected for testing; it must be a callable
    producing an async context manager whose value exposes ``arun``.
    """

    def __init__(self, crawler_factory: Any | None = None) -> None:
        if crawler_factory is None and AsyncWebCrawler is None:
            raise RuntimeError(
                "crawl4ai is not installed; run `pip install nhs-webscraper[crawl]` "
                "and `crawl4ai-setup` to use Crawl4AIBackend"
            )
        self._crawler_factory = (
            crawler_factory if crawler_factory is not None else AsyncWebCrawler
        )

    async def scrape(self, url: str) -> Page:
        """Fetch a single page and convert it to a domain ``Page``."""
        async with self._crawler_factory() as crawler:
            result = await crawler.arun(url=url, config=CrawlerRunConfig())
        return self._to_page(result)

    async def crawl(
        self, seed: str, options: CrawlOptions | None = None
    ) -> Sequence[Page]:
        """Breadth-first crawl from ``seed``, bounded by ``options``.

        Unsuccessful results are skipped rather than failing the crawl:
        a single broken page must not lose the rest of a trust region.
        """
        options = options or CrawlOptions()
        config = CrawlerRunConfig(
            deep_crawl_strategy=BFSDeepCrawlStrategy(
                max_depth=options.max_depth,
                max_pages=options.limit,
            )
        )
        async with self._crawler_factory() as crawler:
            results = await crawler.arun(url=seed, config=config)
        return [
            self._to_page(result)
            for result in results
            if getattr(result, "success", True)
        ]

    @staticmethod
    def _to_page(result: Any) -> Page:
        """Convert a Crawl4AI ``CrawlResult`` into a domain ``Page``.

        ``cleaned_html`` is preferred over raw ``html``; newer Crawl4AI
        versions wrap markdown in a result object, which is unwrapped to
        its ``raw_markdown`` string.
        """
        if not getattr(result, "success", True):
            raise CrawlError(
                f"crawl failed for {result.url}: "
                f"{getattr(result, 'error_message', 'unknown error')}"
            )
        html = getattr(result, "cleaned_html", None) or getattr(result, "html", None) or ""
        markdown = getattr(result, "markdown", None)
        if markdown is not None and not isinstance(markdown, str):
            markdown = getattr(markdown, "raw_markdown", str(markdown))
        metadata = dict(getattr(result, "metadata", None) or {})
        return Page(url=result.url, html=html, markdown=markdown, metadata=metadata)
