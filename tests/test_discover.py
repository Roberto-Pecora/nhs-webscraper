"""Offline tests for seed discovery and the CLI ``--discover`` mode."""

from __future__ import annotations

import asyncio

from nhs_scraper.cli import main as cli_main
from nhs_scraper.cli import parse_args
from nhs_scraper.domain import Page
from nhs_scraper.pipeline.discover import (
    BASE_URL,
    discover_region_urls,
    discover_seeds,
    discover_trust_seeds,
)

TRUST_URL = "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/"
OXFORD_URL = "https://www.myplannedcare.nhs.uk/seast/oxford-university/"
SEAST_URL = "https://www.myplannedcare.nhs.uk/seast/"

#: Region slugs in homepage-fixture order, mirroring the live site.
REGION_SLUGS = ("east", "london", "mids", "ney", "nwest", "seast", "swest")


class FakeBackend:
    """Serves pages by URL for scrape(); records crawl calls."""

    def __init__(self, pages_by_url: dict[str, Page]):
        self._pages = pages_by_url
        self.crawl_calls: list[str] = []

    async def scrape(self, url: str) -> Page:
        return self._pages[url]

    async def crawl(self, seed: str, options=None) -> list[Page]:
        self.crawl_calls.append(seed)
        return [self._pages[seed]]


def page(html: str, url: str) -> Page:
    return Page(url=url, html=html)


def empty_region_pages(*exclude: str) -> dict[str, Page]:
    """Empty region pages for every slug except those excluded."""
    return {
        f"{BASE_URL}{slug}/": page("<html><body></body></html>", f"{BASE_URL}{slug}/")
        for slug in REGION_SLUGS
        if slug not in exclude
    }


def discover_backend(load_fixture, oxford_html: str | None = None) -> FakeBackend:
    """Backend wired for a full --discover run over the fixtures.

    Oxford defaults to serving the same Royal Berkshire HTML — the
    dedupe-across-seeds scenario.
    """
    trust_html = load_fixture("trust_page_royal_berkshire.html")
    return FakeBackend(
        {
            BASE_URL: page(load_fixture("homepage.html"), BASE_URL),
            SEAST_URL: page(load_fixture("region_page_seast.html"), SEAST_URL),
            TRUST_URL: page(trust_html, TRUST_URL),
            OXFORD_URL: page(
                oxford_html if oxford_html is not None else trust_html, OXFORD_URL
            ),
            **empty_region_pages("seast"),
        }
    )


class TestDiscoverRegionUrls:
    def test_homepage_fixture_yields_all_regions_in_order(self, load_fixture):
        urls = discover_region_urls(load_fixture("homepage.html"))

        assert urls == [f"{BASE_URL}{slug}/" for slug in REGION_SLUGS]

    def test_duplicates_external_and_utility_links_excluded(self, load_fixture):
        urls = discover_region_urls(load_fixture("homepage.html"))

        assert urls.count(f"{BASE_URL}london/") == 1  # duplicate collapsed
        assert not any("twitter.com" in u or "other-site" in u for u in urls)
        assert f"{BASE_URL}find-my-hospital/" not in urls  # not a region slug

    def test_relative_href_resolved_against_base(self):
        assert discover_region_urls('<a href="seast/">SE</a>') == [f"{BASE_URL}seast/"]

    def test_trailing_nbsp_in_href_is_stripped(self):
        # Live-site regression: a trailing U+00A0 (&nbsp;) on an anchor's
        # href must not survive into the yielded URL.
        html = '<a href="seast\xa0">SE</a>'
        assert discover_region_urls(html) == [f"{BASE_URL}seast/"]

    def test_whitespace_only_href_is_skipped(self):
        html = '<a href="\xa0">blank</a><a href="seast/">SE</a>'
        assert discover_region_urls(html) == [f"{BASE_URL}seast/"]


class TestDiscoverTrustSeeds:
    def test_region_fixture_yields_trust_seeds_with_region_name(self, load_fixture):
        seeds = discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))

        assert seeds == [
            (TRUST_URL, "South East"),
            (OXFORD_URL, "South East"),
        ]

    def test_traps_are_excluded(self, load_fixture):
        seeds = discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))
        urls = [url for url, _ in seeds]

        assert urls.count(TRUST_URL) == 1                # duplicate collapsed
        assert SEAST_URL not in urls                     # self link
        assert not any("cardiology" in u for u in urls)  # too deep
        assert not any("/london/" in u for u in urls)    # wrong region

    def test_trailing_nbsp_on_trust_link_yields_clean_seed(self):
        # Live-site regression (mid-south-essex): a trailing U+00A0 on a
        # trust anchor's href must not produce a malformed seed URL that
        # later fails WaitingTimeRecord's canonical-URL validation.
        html = '<a href="/east/mid-south-essex/\xa0">Mid and South Essex NHS Foundation Trust</a>'
        seeds = discover_trust_seeds(f"{BASE_URL}east/", html)

        assert seeds == [(f"{BASE_URL}east/mid-south-essex/", "East of England")]

    def test_unknown_slug_falls_back_to_slug_as_region(self):
        seeds = discover_trust_seeds(
            f"{BASE_URL}unknown/", '<a href="/unknown/trust-x/">X NHS Trust</a>'
        )
        assert seeds == [(f"{BASE_URL}unknown/trust-x/", "unknown")]

    def test_independent_providers_excluded_from_region_fixture(self, load_fixture):
        # region_page_seast.html carries real-pattern independent-provider
        # traps (Spamedica, Nuffield, Circle) alongside the two genuine
        # trusts — only the trusts should survive.
        seeds = discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))
        urls = [url for url, _ in seeds]

        assert urls == [TRUST_URL, OXFORD_URL]
        assert not any("spamedica" in u for u in urls)
        assert not any("nuffield" in u for u in urls)
        assert not any("circle" in u for u in urls)

    def test_link_text_mix_of_nhs_trusts_and_independent_providers(self):
        # Modelled on the live South East / London region pages: NHS
        # trust link text always ends "NHS Trust"/"NHS Foundation Trust";
        # independent providers follow a "Location - Brand" pattern with
        # an en dash and no such suffix.
        html = """
        <a href="/seast/royal-berkshire/">Royal Berkshire NHS Foundation Trust</a>
        <a href="/seast/isle-of-wight/">Isle of Wight NHS Trust</a>
        <a href="/seast/portsmouth-spamedica/">Portsmouth – Spamedica</a>
        <a href="/seast/wessex-nuffield/">Wessex – Nuffield</a>
        <a href="/seast/runnymede-circle/">The Runnymede Hospital – Circle</a>
        <a href="/seast/ramsay/">Berkshire – Ramsay</a>
        """
        seeds = discover_trust_seeds(SEAST_URL, html)

        assert seeds == [
            (f"{BASE_URL}seast/royal-berkshire/", "South East"),
            (f"{BASE_URL}seast/isle-of-wight/", "South East"),
        ]

    def test_real_leaked_independent_providers_excluded(self, load_fixture):
        # Regression for a real --discover run against the live South East
        # region page that produced these exact independent-provider seeds
        # despite the suffix filter. Root-caused to the fixture not yet
        # covering these specific slugs, not a filter bug (see discover.py
        # module docstring); this locks the real-world case in going forward.
        seeds = discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))
        urls = [url for url, _ in seeds]

        leaked_slugs = (
            "ashtead-hospital-ramsay",
            "alexandra-hospital-spire",
            "benenden-hospital",
            "basingstoke-chec",
            "berkshire-independent-hospital-ramsay",
        )
        for slug in leaked_slugs:
            assert not any(slug in u for u in urls), f"{slug} leaked into trust seeds"

    def test_trust_seed_count_logged(self, load_fixture, caplog):
        with caplog.at_level("INFO", logger="nhs_scraper.pipeline.discover"):
            discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))

        assert any(
            "candidate provider links" in record.message and "kept as NHS trusts" in record.message
            for record in caplog.records
        )


class TestDiscoverSeeds:
    def test_orchestrates_homepage_then_region_scrapes(self, load_fixture):
        backend = FakeBackend(
            {
                BASE_URL: page(load_fixture("homepage.html"), BASE_URL),
                **empty_region_pages("seast"),
                SEAST_URL: page(load_fixture("region_page_seast.html"), SEAST_URL),
            }
        )

        seeds = asyncio.run(discover_seeds(backend))

        assert seeds == [
            (TRUST_URL, "South East"),
            (OXFORD_URL, "South East"),
        ]

    def test_empty_homepage_raises(self):
        backend = FakeBackend(
            {BASE_URL: page("<html><body>no links</body></html>", BASE_URL)}
        )

        try:
            asyncio.run(discover_seeds(backend))
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "no region links" in str(exc)

    def test_region_pages_without_trusts_raise(self, load_fixture):
        backend = FakeBackend(
            {
                BASE_URL: page(load_fixture("homepage.html"), BASE_URL),
                **empty_region_pages(),
            }
        )

        try:
            asyncio.run(discover_seeds(backend))
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "no trust links" in str(exc)


class TestCliDiscover:
    def test_flag_parses(self):
        assert parse_args(["--discover"]).discover is True
        assert parse_args([]).discover is False

    def test_discover_and_seed_conflict_returns_1(self, capsys):
        exit_code = cli_main(["--discover", "--seed", f"{TRUST_URL}=South East"])

        assert exit_code == 1
        assert "mutually exclusive" in capsys.readouterr().out

    def test_discovery_failure_returns_1_without_fallback(self, monkeypatch, capsys):
        backend = FakeBackend({BASE_URL: page("<html><body>empty</body></html>", BASE_URL)})
        monkeypatch.setattr("nhs_scraper.cli.build_backend", lambda *a, **kw: backend)

        exit_code = cli_main(["--discover"])

        assert exit_code == 1
        out = capsys.readouterr().out
        assert "seed discovery failed" in out
        assert "no region links" in out
        assert backend.crawl_calls == []  # never fell through to a crawl

    def test_discover_full_run_dedupes_identical_records(
        self, monkeypatch, tmp_path, load_fixture, capsys
    ):
        # Both seeds serve the same fixture HTML: the second trust's 4
        # records are exact duplicates and normalise_records collapses
        # them — dedupe across seeds is the intended behaviour.
        monkeypatch.setattr(
            "nhs_scraper.cli.build_backend",
            lambda *a, **kw: discover_backend(load_fixture),
        )
        output = tmp_path / "full.csv"

        exit_code = cli_main(["--discover", "--output", str(output)])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "discovered 2 trust seeds" in out
        assert "4 records" in out  # 4 golden records, deduped across seeds
        assert output.exists()

    def test_discover_full_run_accumulates_distinct_records(
        self, monkeypatch, tmp_path, load_fixture, capsys
    ):
        # Two different URLs serving identical HTML dedupe to the same
        # records, so the provider in the dedupe key comes from the page
        # <h1>. Prepending text inside the h1 tag changes the provider —
        # and thus the dedupe key — without touching any parsed numbers.
        oxford_html = load_fixture("trust_page_royal_berkshire.html").replace(
            "<h1>", "<h1>Oxford University Hospitals — ", 1
        )
        assert oxford_html != load_fixture("trust_page_royal_berkshire.html")
        monkeypatch.setattr(
            "nhs_scraper.cli.build_backend",
            lambda *a, **kw: discover_backend(load_fixture, oxford_html),
        )
        output = tmp_path / "full.csv"

        exit_code = cli_main(["--discover", "--output", str(output)])

        assert exit_code == 0
        assert "8 records" in capsys.readouterr().out
        assert output.exists()
