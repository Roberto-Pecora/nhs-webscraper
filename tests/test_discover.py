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
SEAST_URL = "https://www.myplannedcare.nhs.uk/seast/"


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


class TestDiscoverRegionUrls:
    def test_homepage_fixture_yields_all_regions_in_order(self, load_fixture):
        urls = discover_region_urls(load_fixture("homepage.html"))

        assert urls == [
            f"{BASE_URL}{slug}/"
            for slug in ("east", "london", "midlands", "neast", "nwest", "seast", "swest")
        ]

    def test_duplicates_external_and_utility_links_excluded(self, load_fixture):
        urls = discover_region_urls(load_fixture("homepage.html"))

        assert urls.count(f"{BASE_URL}london/") == 1  # duplicate collapsed
        assert not any("twitter.com" in u or "other-site" in u for u in urls)
        assert f"{BASE_URL}find-my-hospital/" not in urls  # not a region slug

    def test_relative_href_resolved_against_base(self):
        assert discover_region_urls('<a href="seast/">SE</a>') == [f"{BASE_URL}seast/"]


class TestDiscoverTrustSeeds:
    def test_region_fixture_yields_trust_seeds_with_region_name(self, load_fixture):
        seeds = discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))

        assert seeds == [
            (TRUST_URL, "South East"),
            ("https://www.myplannedcare.nhs.uk/seast/oxford-university/", "South East"),
        ]

    def test_traps_are_excluded(self, load_fixture):
        urls = [u for u, _ in discover_trust_seeds(SEAST_URL, load_fixture("region_page_seast.html"))]

        assert urls.count(TRUST_URL) == 1          # duplicate collapsed
        assert SEAST_URL not in urls               # self link
        assert not any("cardiology" in u for u in urls)   # too deep
        assert not any("/london/" in u for u in urls)     # wrong region

    def test_unknown_slug_falls_back_to_slug_as_region(self):
        seeds = discover_trust_seeds(
            f"{BASE_URL}unknown/", '<a href="/unknown/trust-x/">X</a>'
        )
        assert seeds == [(f"{BASE_URL}unknown/trust-x/", "unknown")]


class TestDiscoverSeeds:
    def test_orchestrates_homepage_then_region_scrapes(self, load_fixture):
        backend = FakeBackend(
            {
                BASE_URL: page(load_fixture("homepage.html"), BASE_URL),
                **{
                    f"{BASE_URL}{slug}/": page("<html><body></body></html>", f"{BASE_URL}{slug}/")
                    for slug in ("east", "london", "midlands", "neast", "nwest", "swest")
                },
                SEAST_URL: page(load_fixture("region_page_seast.html"), SEAST_URL),
            }
        )

        seeds = asyncio.run(discover_seeds(backend))

        assert seeds == [
            (TRUST_URL, "South East"),
            ("https://www.myplannedcare.nhs.uk/seast/oxford-university/", "South East"),
        ]

    def test_empty_homepage_raises(self):
        backend = FakeBackend({BASE_URL: page("<html><body>no links</body></html>", BASE_URL)})

        try:
            asyncio.run(discover_seeds(backend))
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "no region links" in str(exc)

    def test_region_pages_without_trusts_raise(self, load_fixture):
        empty = "<html><body>nothing here</body></html>"
        backend = FakeBackend(
            {
                BASE_URL: page(load_fixture("homepage.html"), BASE_URL),
                **{
                    f"{BASE_URL}{slug}/": page(empty, f"{BASE_URL}{slug}/")
                    for slug in ("east", "london", "midlands", "neast", "nwest", "seast", "swest")
                },
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

    def test_discover_full_run_writes_csv(
        self, monkeypatch, tmp_path, load_fixture, capsys
    ):
        trust_page = page(load_fixture("trust_page_royal_berkshire.html"), TRUST_URL)
        backend = FakeBackend(
            {
                BASE_URL: page(load_fixture("homepage.html"), BASE_URL),
                SEAST_URL: page(load_fixture("region_page_seast.html"), SEAST_URL),
                TRUST_URL: trust_page,
                **{
                    f"{BASE_URL}{slug}/": page("<html><body></body></html>", f"{BASE_URL}{slug}/")
                    for slug in ("east", "london", "midlands", "neast", "nwest", "swest")
                },
            }
        )
        # Oxford is discovered as a seed but has no fixture page; give the
        # crawl the royal-berkshire page content under that URL too.
        backend._pages["https://www.myplannedcare.nhs.uk/seast/oxford-university/"] = page(
            load_fixture("trust_page_royal_berkshire.html"),
            "https://www.myplannedcare.nhs.uk/seast/oxford-university/",
        )
        monkeypatch.setattr("nhs_scraper.cli.build_backend", lambda *a, **kw: backend)
        output = tmp_path / "full.csv"

        exit_code = cli_main(["--discover", "--output", str(output)])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "discovered 2 trust seeds" in out
        assert "8 records" in out  # 4 golden records x 2 discovered trusts
        assert output.exists()
