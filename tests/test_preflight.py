"""Offline tests for the pre-flight layout probe and its pipeline wiring.

The drifted fixture proves the probe catches a restructured site; the
pipeline tests prove drift aborts *before* any crawl call is made.
"""

from __future__ import annotations

import asyncio

import pytest

from nhs_scraper.cli import main as cli_main
from nhs_scraper.cli import parse_args
from nhs_scraper.domain import Page
from nhs_scraper.pipeline.preflight import LayoutDriftError, probe_layout
from nhs_scraper.pipeline.run import run_pipeline
from nhs_scraper.ports import CrawlOptions

TRUST_URL = "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/"

ALL_FIVE_FAILURES = {
    "no <h1> provider heading found",
    "no <div class='inner_details_holder'> specialty blocks found",
    "no recognised waiting-times table captions found",
    "no waiting-time tables with 'Average waiting time' header found",
    "no 'This page was last updated on ...' footer found",
}


class FakeBackend:
    def __init__(self, pages_by_seed: dict[str, list[Page]]):
        self._pages_by_seed = pages_by_seed
        self.crawl_calls: list[str] = []

    async def scrape(self, url: str) -> Page:
        return self._pages_by_seed[url][0]

    async def crawl(self, seed: str, options: CrawlOptions | None = None) -> list[Page]:
        self.crawl_calls.append(seed)
        return self._pages_by_seed.get(seed, [])


def make_page(html: str, url: str = TRUST_URL) -> Page:
    return Page(url=url, html=html)


class TestProbeLayout:
    def test_known_good_fixture_passes(self, load_fixture):
        result = probe_layout(make_page(load_fixture("trust_page_royal_berkshire.html")))

        assert result.ok
        assert result.failures == ()

    def test_drifted_fixture_reports_every_failure(self, load_fixture):
        result = probe_layout(make_page(load_fixture("trust_page_drifted.html")))

        assert not result.ok
        assert set(result.failures) == ALL_FIVE_FAILURES

    def test_partial_drift_reports_single_failure(self, load_fixture):
        html = load_fixture("trust_page_royal_berkshire.html").replace(
            "This page was last updated on 7 August 2026", "Updated 7 Aug 2026"
        )
        result = probe_layout(make_page(html))

        assert not result.ok
        assert result.failures == ("no 'This page was last updated on ...' footer found",)

    def test_structurally_valid_but_unextractable_page_flagged(self):
        # Tables and captions present (structural checks pass) but every
        # cell is n/a, so the extractor yields nothing — end-to-end signal.
        html = (
            "<html><body><article><header><h1>Trust X</h1></header>"
            "<div class='inner_details_holder'><div>"
            "<h3 class='nhsblue-text0'>ENT - Waiting Times</h3>"
            "<table class='waiting-times-data'><caption>Treatment</caption>"
            "<tr><th>Average waiting time for treatment</th><td><em>n/a</em></td></tr>"
            "</table></div></div>"
            "<ul><li>This page was last updated on 7 August 2026.</li></ul>"
            "</article></body></html>"
        )
        result = probe_layout(make_page(html, url="https://www.myplannedcare.nhs.uk/x/"))

        assert not result.ok
        assert result.failures == (
            "extractor produced no records from a structurally valid page",
        )


class TestPipelinePreflight:
    def test_drift_aborts_before_any_crawl(self, load_fixture):
        drifted = make_page(load_fixture("trust_page_drifted.html"))
        backend = FakeBackend({TRUST_URL: [drifted]})

        with pytest.raises(LayoutDriftError) as excinfo:
            asyncio.run(run_pipeline(backend, [(TRUST_URL, "South East")]))

        assert backend.crawl_calls == []  # no crawl attempted
        assert excinfo.value.url == TRUST_URL
        assert len(excinfo.value.failures) == 5

    def test_good_layout_proceeds_to_golden_output(self, load_fixture, load_golden):
        page = make_page(load_fixture("trust_page_royal_berkshire.html"))
        backend = FakeBackend({TRUST_URL: [page]})

        result = asyncio.run(run_pipeline(backend, [(TRUST_URL, "South East")]))

        expected = load_golden("royal_berkshire_expected.json")
        assert [record.to_dict() for record in result.records] == expected
        assert backend.crawl_calls == [TRUST_URL]

    def test_preflight_disabled_preserves_lenient_behaviour(self, load_fixture):
        drifted = make_page(load_fixture("trust_page_drifted.html"))
        backend = FakeBackend({TRUST_URL: [drifted]})

        result = asyncio.run(
            run_pipeline(backend, [(TRUST_URL, "South East")], preflight=False)
        )

        assert result.records == []
        assert backend.crawl_calls == [TRUST_URL]


class TestCliPreflight:
    def test_no_preflight_flag(self):
        assert parse_args(["--no-preflight"]).no_preflight is True
        assert parse_args([]).no_preflight is False

    def test_main_returns_2_with_named_failures_on_drift(
        self, monkeypatch, load_fixture, capsys
    ):
        drifted = make_page(load_fixture("trust_page_drifted.html"))
        backend = FakeBackend({TRUST_URL: [drifted]})
        monkeypatch.setattr("nhs_scraper.cli.build_backend", lambda *a, **kw: backend)

        exit_code = cli_main(["--seed", f"{TRUST_URL}=South East"])

        assert exit_code == 2
        out = capsys.readouterr().out
        assert "layout drift detected" in out
        assert "no <h1> provider heading found" in out

    def test_main_success_path_writes_csv(
        self, monkeypatch, tmp_path, load_fixture, capsys
    ):
        page = make_page(load_fixture("trust_page_royal_berkshire.html"))
        backend = FakeBackend({TRUST_URL: [page]})
        monkeypatch.setattr("nhs_scraper.cli.build_backend", lambda *a, **kw: backend)
        output = tmp_path / "out.csv"

        exit_code = cli_main(
            ["--seed", f"{TRUST_URL}=South East", "--output", str(output)]
        )

        assert exit_code == 0
        assert output.exists()
        assert "2 records" in capsys.readouterr().out
