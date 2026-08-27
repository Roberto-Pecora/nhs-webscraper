"""Integration tests for pipeline orchestration, driven by a fake backend.

The keystone test runs the full crawl -> extract -> normalise chain over
the characterisation fixture and expects the golden dataset back — the
whole pipeline, offline, no browser.
"""

from __future__ import annotations

import asyncio

import pytest

from nhs_scraper.domain import Page
from nhs_scraper.pipeline.run import run_pipeline
from nhs_scraper.ports import CrawlOptions

TRUST_URL = "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/"


class FakeBackend:
    def __init__(self, pages_by_seed: dict[str, list[Page]]):
        self._pages_by_seed = pages_by_seed

    async def scrape(self, url: str) -> Page:
        return self._pages_by_seed[url][0]

    async def crawl(self, seed: str, options: CrawlOptions | None = None) -> list[Page]:
        return self._pages_by_seed.get(seed, [])


class TestGoldenPipeline:
    def test_full_pipeline_reproduces_golden_dataset(self, load_fixture, load_golden):
        page = Page(url=TRUST_URL, html=load_fixture("trust_page_royal_berkshire.html"))
        backend = FakeBackend({TRUST_URL: [page]})

        result = asyncio.run(run_pipeline(backend, [(TRUST_URL, "South East")]))

        expected = load_golden("royal_berkshire_expected.json")
        assert [record.to_dict() for record in result.records] == expected

    def test_result_carries_run_provenance(self, load_fixture):
        page = Page(url=TRUST_URL, html=load_fixture("trust_page_royal_berkshire.html"))
        backend = FakeBackend({TRUST_URL: [page]})

        result = asyncio.run(run_pipeline(backend, [(TRUST_URL, "South East")]))

        assert result.run.backend == "FakeBackend"
        assert result.run.seed_url == TRUST_URL
        assert result.run.run_id
        assert result.run.started_at.tzinfo is not None


class TestSeedHandling:
    def test_region_is_threaded_into_records(self, load_fixture):
        page = Page(url=TRUST_URL, html=load_fixture("trust_page_royal_berkshire.html"))
        backend = FakeBackend({TRUST_URL: [page]})

        result = asyncio.run(run_pipeline(backend, [(TRUST_URL, "London")]))

        assert {record.region for record in result.records} == {"London"}

    def test_multiple_seeds_aggregate(self, load_fixture):
        other_url = "https://www.myplannedcare.nhs.uk/london/example/"
        fixture_html = load_fixture("trust_page_royal_berkshire.html")
        backend = FakeBackend(
            {
                TRUST_URL: [Page(url=TRUST_URL, html=fixture_html)],
                other_url: [Page(url=other_url, html=fixture_html)],
            }
        )

        result = asyncio.run(
            run_pipeline(backend, [(TRUST_URL, "South East"), (other_url, "London")])
        )

        # Same provider/specialty/metric under two regions: not duplicates.
        assert len(result.records) == 8
        assert {record.region for record in result.records} == {"South East", "London"}

    def test_empty_seed_list_rejected(self):
        with pytest.raises(ValueError, match="at least one seed"):
            asyncio.run(run_pipeline(FakeBackend({}), []))

    def test_crawl_with_no_pages_yields_no_records(self):
        # Preflight is disabled here: this test isolates crawl behaviour,
        # and the empty backend has no canary page to probe. Preflight
        # itself is covered by tests/test_preflight.py.
        result = asyncio.run(
            run_pipeline(
                FakeBackend({}),
                [("https://www.myplannedcare.nhs.uk/x/", "London")],
                preflight=False,
            )
        )
        assert result.records == []


class ConcurrencyTrackingBackend:
    """Fake backend that proves seeds overlap in flight and stays bounded.

    ``crawl`` yields control (``asyncio.sleep``) mid-call so overlapping
    seeds actually interleave under a real event loop — a purely
    sequential loop would never show ``max_in_flight > 1`` here. It also
    mimics ``Crawl4AIBackend``: ``last_failed_pages`` is set on ``self``
    *after* an ``await`` (the same shape as the real backend's
    ``async with ... __aexit__`` gap before the attribute write), so a
    test reading it too late would observe another seed's value.
    """

    def __init__(self, failures_by_seed: dict[str, tuple[str, ...]]):
        self._failures_by_seed = failures_by_seed
        self.last_failed_pages: tuple[str, ...] = ()
        self.in_flight = 0
        self.max_in_flight = 0
        self.call_count = 0

    async def scrape(self, url: str) -> Page:
        return Page(url=url, html="<html></html>")

    async def crawl(self, seed: str, options: CrawlOptions | None = None) -> list[Page]:
        self.call_count += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)  # let other seeds' crawl() interleave
        self.in_flight -= 1
        self.last_failed_pages = self._failures_by_seed.get(seed, ())
        return [Page(url=seed, html="<html></html>")]


class TestConcurrentSeeds:
    def test_seeds_run_concurrently_not_sequentially(self):
        seeds = [(f"https://www.myplannedcare.nhs.uk/x{i}/", "London") for i in range(6)]
        backend = ConcurrencyTrackingBackend({})

        asyncio.run(
            run_pipeline(backend, seeds, CrawlOptions(concurrency=6), preflight=False)
        )

        # A sequential loop can never have more than one crawl() in flight;
        # this fails if someone reverts to the plain `for` loop.
        assert backend.max_in_flight > 1
        assert backend.call_count == len(seeds)

    def test_concurrency_is_bounded_by_options(self):
        seeds = [(f"https://www.myplannedcare.nhs.uk/x{i}/", "London") for i in range(10)]
        backend = ConcurrencyTrackingBackend({})

        asyncio.run(
            run_pipeline(backend, seeds, CrawlOptions(concurrency=3), preflight=False)
        )

        assert backend.max_in_flight <= 3
        assert backend.call_count == len(seeds)

    def test_failed_pages_collected_completely_across_concurrent_seeds(self):
        urls = [f"https://www.myplannedcare.nhs.uk/x{i}/" for i in range(5)]
        seeds = [(url, "London") for url in urls]
        # Every seed reports its own distinct failed page: a naive
        # "read backend.last_failed_pages once after gather" approach
        # would only see the last seed's value and drop the rest.
        failures_by_seed = {url: (f"{url}broken-page/",) for url in urls}
        backend = ConcurrencyTrackingBackend(failures_by_seed)

        result = asyncio.run(
            run_pipeline(backend, seeds, CrawlOptions(concurrency=5), preflight=False)
        )

        expected = {f"{url}broken-page/" for url in urls}
        assert set(result.failed_pages) == expected
        assert len(result.failed_pages) == len(urls)
