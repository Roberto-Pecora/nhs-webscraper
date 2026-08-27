"""Ports: interfaces between the pure pipeline core and crawl backends.

The port is async-native because the chosen backend (Crawl4AI) is built on
async Playwright; faking a synchronous interface would fight the library.
Tests drive the coroutines with ``asyncio.run`` so no pytest-asyncio
dependency is required.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nhs_scraper.domain import Page


@dataclass(frozen=True)
class CrawlOptions:
    """Constraints applied to a multi-page crawl."""

    limit: int = 100
    max_depth: int = 2
    allow_subdomains: bool = False
    concurrency: int = 8
    """Max number of seeds crawled concurrently by ``run_pipeline``.

    Bounded rather than unbounded so a full-site ``--discover`` run (100+
    trusts) doesn't hammer the live NHS site or exceed the backend's own
    connection pool. 8 is a conservative default for a public site.
    """

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError(f"limit must be >= 1, got {self.limit}")
        if self.max_depth < 0:
            raise ValueError(f"max_depth must be >= 0, got {self.max_depth}")
        if self.concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {self.concurrency}")


@dataclass(frozen=True)
class RetryPolicy:
    """Retry behaviour for transient crawl failures.

    Backoff is linear (``backoff_seconds * attempt``): polite towards a
    public NHS site, where aggressive exponential retries are the wrong
    posture. Validation failures are never retried — only transient
    transport errors and soft (unsuccessful-result) failures.
    """

    attempts: int = 3
    backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError(f"attempts must be >= 1, got {self.attempts}")
        if self.backoff_seconds < 0:
            raise ValueError(
                f"backoff_seconds must be >= 0, got {self.backoff_seconds}"
            )


@runtime_checkable
class CrawlBackend(Protocol):
    """Async contract every crawl backend must satisfy.

    Implementations return domain ``Page`` objects; they never leak
    backend-specific response types into the pipeline.
    """

    async def scrape(self, url: str) -> Page:
        """Fetch a single page."""
        ...

    async def crawl(self, seed: str, options: CrawlOptions | None = None) -> Sequence[Page]:
        """Fetch ``seed`` and linked pages, bounded by ``options``."""
        ...
