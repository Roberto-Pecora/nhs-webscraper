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
