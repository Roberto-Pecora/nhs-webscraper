"""Pipeline orchestration: crawl -> extract -> normalise, with provenance.

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
from nhs_scraper.ports import CrawlBackend, CrawlOptions

logger = logging.getLogger(__name__)

#: A seed is a (url, region) pair: the region is threaded into every
#: record extracted from pages discovered under that URL.
Seed = tuple[str, str]


@dataclass(frozen=True)
class PipelineResult:
    """The outcome of one pipeline execution: provenance plus records."""

    run: CrawlRun
    records: list[WaitingTimeRecord]


async def run_pipeline(
    backend: CrawlBackend,
    seeds: Iterable[Seed],
    options: CrawlOptions | None = None,
) -> PipelineResult:
    """Crawl every seed, extract waiting times, and normalise the result.

    Extraction failures surface as absent records (the extractor's
    contract), never as exceptions; backend failures propagate — a failed
    crawl of a whole region is worth failing loudly.
    """
    seeds = list(seeds)
    if not seeds:
        raise ValueError("at least one seed is required")

    run = CrawlRun(seed_url=seeds[0][0], backend=type(backend).__name__)
    records: list[WaitingTimeRecord] = []

    for url, region in seeds:
        pages: Sequence = await backend.crawl(url, options)
        logger.info("crawl of %s returned %d pages", url, len(pages))
        for page in pages:
            records.extend(extract_waiting_times(page, region=region))

    normalised = normalise_records(records)
    logger.info("run %s: %d records after normalisation", run.run_id, len(normalised))
    return PipelineResult(run=run, records=normalised)
