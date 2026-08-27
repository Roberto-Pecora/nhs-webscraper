"""Crawl4AI backend: adapts ``AsyncWebCrawler`` to the ``CrawlBackend`` port.

crawl4ai is an optional dependency (install the ``crawl`` extra). It is
imported with a graceful fallback so the rest of the package — and the
whole unit-test suite — works without it; unit tests monkeypatch the
module attributes and inject a fake crawler, so no browser is required
offline. Constructing the backend without crawl4ai (and without an
injected factory) raises ``RuntimeError`` with the remedy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

from nhs_scraper.domain import Page
from nhs_scraper.ports import CrawlOptions, RetryPolicy

try:  # pragma: no cover - the real import is exercised by integration tests
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    from crawl4ai.deep_crawling.filters import DomainFilter, FilterChain, URLPatternFilter
except ImportError:  # pragma: no cover
    AsyncWebCrawler = None  # type: ignore[assignment]
    CrawlerRunConfig = None  # type: ignore[assignment]
    BFSDeepCrawlStrategy = None  # type: ignore[assignment]
    DomainFilter = None  # type: ignore[assignment]
    FilterChain = None  # type: ignore[assignment]
    URLPatternFilter = None  # type: ignore[assignment]


class CrawlError(RuntimeError):
    """Raised when Crawl4AI reports an unsuccessful scrape."""


class _ExactHostFilter:
    """Restricts a deep crawl to one exact host — no subdomains.

    Crawl4AI's own ``DomainFilter`` always treats an allowed domain as also
    matching its subdomains, so it can't express "this host only" on its
    own. This is a plain, duck-typed filter (``FilterChain`` only requires
    an ``apply(url) -> bool`` method) rather than a subclass of a Crawl4AI
    filter, so it doesn't depend on or override any library internals.
    """

    def __init__(self, host: str) -> None:
        self._host = host.lower()

    def apply(self, url: str) -> bool:
        return urlsplit(url).hostname == self._host


class Crawl4AIBackend:
    """``CrawlBackend`` implementation backed by Crawl4AI.

    ``crawler_factory`` may be injected for testing; it must be a callable
    producing an async context manager whose value exposes ``arun``.

    ``retry_policy`` enables retries of *transient* failures (raised
    transport errors and unsuccessful results). ``sleeper`` is a testing
    hook for the backoff delay; production uses ``asyncio.sleep``.

    ``last_failed_pages`` lists page URLs whose crawl results were
    unsuccessful (after any retries) in the most recent ``crawl`` call —
    failure telemetry the pipeline surfaces instead of dropping silently.
    """

    def __init__(
        self,
        crawler_factory: Any | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if crawler_factory is None and AsyncWebCrawler is None:
            raise RuntimeError(
                "crawl4ai is not installed; run `pip install nhs-webscraper[crawl]` "
                "and `crawl4ai-setup` to use Crawl4AIBackend"
            )
        self._crawler_factory = (
            crawler_factory if crawler_factory is not None else AsyncWebCrawler
        )
        self._retry_policy = retry_policy
        self._sleep = sleeper if sleeper is not None else asyncio.sleep
        self.last_failed_pages: tuple[str, ...] = ()

    async def _arun_with_retries(self, crawler: Any, url: str, config: Any) -> Any:
        """Call ``arun``, retrying transient failures per the retry policy.

        Without a policy exactly one attempt is made. Exhaustion raises
        the last error: ``CrawlError`` for soft (unsuccessful-result)
        failures, the original exception for transport errors.
        """
        policy = self._retry_policy or RetryPolicy(attempts=1)
        last_error: Exception | None = None

        for attempt in range(1, policy.attempts + 1):
            try:
                result = await crawler.arun(url=url, config=config)
            except Exception as exc:  # transient network/browser errors
                last_error = exc
            else:
                if getattr(result, "success", True):
                    return result
                last_error = CrawlError(
                    f"crawl failed for {url}: "
                    f"{getattr(result, 'error_message', 'unknown error')}"
                )
            if attempt < policy.attempts and policy.backoff_seconds:
                await self._sleep(policy.backoff_seconds * attempt)

        raise last_error  # type: ignore[misc]

    def _build_filter_chain(self, seed: str, options: CrawlOptions) -> Any:
        """Build the ``FilterChain`` that bounds a deep crawl from ``seed``.

        Restricts the crawl to the seed's host — subdomains too when
        ``options.allow_subdomains`` is set — and excludes PDF links, which
        the extractor can never use and which otherwise get fetched
        needlessly (NHS trust sites link out to large PDF documents).
        """
        host = urlsplit(seed).hostname or ""
        if options.allow_subdomains:
            domain_filter: Any = DomainFilter(allowed_domains=host)
        else:
            domain_filter = _ExactHostFilter(host)
        pdf_filter = URLPatternFilter(patterns=["*.pdf"], reverse=True)
        return FilterChain(filters=[domain_filter, pdf_filter])

    async def scrape(self, url: str) -> Page:
        """Fetch a single page and convert it to a domain ``Page``."""
        async with self._crawler_factory() as crawler:
            result = await self._arun_with_retries(crawler, url, CrawlerRunConfig())
        return self._to_page(result)

    async def crawl(
        self, seed: str, options: CrawlOptions | None = None
    ) -> Sequence[Page]:
        """Breadth-first crawl from ``seed``, bounded by ``options``.

        Unsuccessful page results are skipped — a single broken page must
        not lose the rest of a trust region — and their URLs are recorded
        on ``last_failed_pages`` so the failure is visible, not silent.
        """
        options = options or CrawlOptions()
        config = CrawlerRunConfig(
            deep_crawl_strategy=BFSDeepCrawlStrategy(
                max_depth=options.max_depth,
                max_pages=options.limit,
                filter_chain=self._build_filter_chain(seed, options),
            )
        )
        async with self._crawler_factory() as crawler:
            results = await self._arun_with_retries(crawler, seed, config)

        self.last_failed_pages = tuple(
            result.url for result in results if not getattr(result, "success", True)
        )
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
