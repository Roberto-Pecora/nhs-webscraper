"""Pipeline orchestration: preflight -> crawl -> extract -> normalise.

The orchestrator depends only on the ``CrawlBackend`` port: it can be
driven by Crawl4AI in production and by an in-memory fake in tests.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from nhs_scraper.domain import CrawlRun, WaitingTimeRecord
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
    records: list[WaitingTimeRecord] = []
    failed_pages: list[str] = []

    for url, region in seeds:
        pages: Sequence = await backend.crawl(url, options)
        logger.info("crawl of %s returned %d pages", url, len(pages))
        failed = tuple(getattr(backend, "last_failed_pages", ()))
        if failed:
            logger.warning("crawl of %s failed for %d pages: %s", url, len(failed), failed)
        failed_pages.extend(failed)
        for page in pages:
            records.extend(extract_waiting_times(page, region=region))

    normalised = normalise_records(records)
    logger.info("run %s: %d records after normalisation", run.run_id, len(normalised))
    return PipelineResult(
        run=run, records=normalised, failed_pages=tuple(failed_pages)
    )
