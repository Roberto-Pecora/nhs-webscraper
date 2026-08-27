"""Pipeline orchestration: preflight -> crawl -> extract -> normalise.

The orchestrator depends only on the ``CrawlBackend`` port: it can be
driven by Crawl4AI in production and by an in-memory fake in tests.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from nhs_scraper.domain import CrawlRun, Page, WaitingTimeRecord
from nhs_scraper.pipeline.extract import extract_waiting_times
from nhs_scraper.pipeline.normalise import normalise_records
from nhs_scraper.pipeline.preflight import LayoutDriftError, probe_layout
from nhs_scraper.ports import CrawlBackend, CrawlOptions

logger = logging.getLogger(__name__)

#: A seed is a (url, region) pair: the region is threaded into every
#: record extracted from pages discovered under that URL.
Seed = tuple[str, str]


@dataclass(frozen=True)
class PipelineResult:
    """The outcome of one pipeline execution: provenance plus records.

    ``failed_pages`` lists page URLs the backend reported as failed
    (after its own retries) — telemetry, not an error: partial results
    are kept, but the gaps are now visible.
    """

    run: CrawlRun
    records: list[WaitingTimeRecord]
    failed_pages: tuple[str, ...] = ()


async def run_pipeline(
    backend: CrawlBackend,
    seeds: Iterable[Seed],
    options: CrawlOptions | None = None,
    *,
    preflight: bool = True,
) -> PipelineResult:
    """Probe the layout, then crawl every seed, extract and normalise.

    With ``preflight=True`` (default) the first seed's page is scraped as
    a canary and probed for the expected layout *before* any deep crawl:
    a drifted site raises ``LayoutDriftError`` naming every failed
    assertion, rather than producing a silently empty CSV.

    Extraction failures surface as absent records (the extractor's
    contract); backend failures propagate — a failed crawl of a whole
    region is worth failing loudly. Per-page failures reported by the
    backend (via the conventional ``last_failed_pages`` attribute) are
    collected into the result's telemetry.
    """
    seeds = list(seeds)
    if not seeds:
        raise ValueError("at least one seed is required")

    if preflight:
        canary_url = seeds[0][0]
        canary = await backend.scrape(canary_url)
        probe = probe_layout(canary)
        if not probe.ok:
            raise LayoutDriftError(canary_url, probe.failures)
        logger.info("preflight probe passed for %s", canary_url)

    run = CrawlRun(seed_url=seeds[0][0], backend=type(backend).__name__)
    concurrency = (options or CrawlOptions()).concurrency
    semaphore = asyncio.Semaphore(concurrency)

    seed_results = await asyncio.gather(
        *(_crawl_seed(backend, semaphore, url, region, options) for url, region in seeds)
    )

    records: list[WaitingTimeRecord] = []
    failed_pages: list[str] = []
    for failed, seed_records in seed_results:
        failed_pages.extend(failed)
        records.extend(seed_records)

    normalised = normalise_records(records)
    logger.info("run %s: %d records after normalisation", run.run_id, len(normalised))
    return PipelineResult(
        run=run, records=normalised, failed_pages=tuple(failed_pages)
    )


async def _crawl_seed(
    backend: CrawlBackend,
    semaphore: asyncio.Semaphore,
    url: str,
    region: str,
    options: CrawlOptions | None,
) -> tuple[tuple[str, ...], list[WaitingTimeRecord]]:
    """Crawl one seed and extract its records, bounded by ``semaphore``.

    ``last_failed_pages`` is read off the backend the instant its own
    ``crawl`` call returns — with no ``await`` in between — so a
    concurrently-running seed's later write can't be observed here first.
    Asyncio only switches tasks at ``await`` points, so this read is safe
    even when several seeds share one backend instance.
    """
    async with semaphore:
        pages: Sequence[Page] = await backend.crawl(url, options)
        failed = tuple(getattr(backend, "last_failed_pages", ()))

    logger.info("crawl of %s returned %d pages", url, len(pages))
    if failed:
        logger.warning("crawl of %s failed for %d pages: %s", url, len(failed), failed)

    records = [
        record
        for page in pages
        for record in extract_waiting_times(page, region=region)
    ]
    return failed, records
