"""Unit tests for the retry policy and failure telemetry — fully offline.

A scripted ``FlakyCrawler`` replays sequences of raised exceptions and
soft (unsuccessful) results; a sleeper hook records backoff delays
without real sleeping.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import nhs_scraper.backends.crawl4ai_backend as backend_module
from nhs_scraper.backends.crawl4ai_backend import Crawl4AIBackend, CrawlError
from nhs_scraper.domain import Page
from nhs_scraper.pipeline.run import run_pipeline
from nhs_scraper.ports import RetryPolicy


class FlakyCrawler:
    """Replays a script: "raise" raises ConnectionError, anything else is returned."""

    def __init__(self, script):
        self._script = list(script)
        self.attempts = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url, config=None):
        self.attempts += 1
        item = self._script.pop(0)
        if item == "raise":
            raise ConnectionError("connection reset by peer")
        return item


def ok(url="https://www.myplannedcare.nhs.uk/x/"):
    return SimpleNamespace(
        url=url, success=True, error_message=None,
        html="<html>raw</html>", cleaned_html="<html>clean</html>",
        markdown=None, metadata={},
    )


def fail(url="https://www.myplannedcare.nhs.uk/x/", message="timeout"):
    return SimpleNamespace(url=url, success=False, error_message=message)


@pytest.fixture()
def stubbed_crawl4ai(monkeypatch):
    monkeypatch.setattr(backend_module, "CrawlerRunConfig", lambda **kw: object())
    monkeypatch.setattr(backend_module, "BFSDeepCrawlStrategy", lambda **kw: object())


@pytest.fixture()
def sleeps():
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    return recorded, fake_sleep


POLICY = RetryPolicy(attempts=3, backoff_seconds=0)


class TestRetryPolicyValidation:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.attempts == 3
        assert policy.backoff_seconds == 2.0

    @pytest.mark.parametrize("attempts", [0, -1])
    def test_invalid_attempts_rejected(self, attempts):
        with pytest.raises(ValueError, match="attempts"):
            RetryPolicy(attempts=attempts)

    def test_negative_backoff_rejected(self):
        with pytest.raises(ValueError, match="backoff"):
            RetryPolicy(backoff_seconds=-1.0)


class TestScrapeRetries:
    def test_transient_exceptions_retried_then_success(self, stubbed_crawl4ai):
        crawler = FlakyCrawler(["raise", "raise", ok()])
        backend = Crawl4AIBackend(lambda: crawler, retry_policy=POLICY)

        page = asyncio.run(backend.scrape("https://x/"))

        assert page.url == "https://www.myplannedcare.nhs.uk/x/"
        assert crawler.attempts == 3

    def test_unsuccessful_results_retried_then_success(self, stubbed_crawl4ai):
        crawler = FlakyCrawler([fail(), ok()])
        backend = Crawl4AIBackend(lambda: crawler, retry_policy=POLICY)

        asyncio.run(backend.scrape("https://x/"))
        assert crawler.attempts == 2

    def test_exhaustion_of_soft_failures_raises_crawl_error(self, stubbed_crawl4ai):
        crawler = FlakyCrawler([fail(), fail(), fail()])
        backend = Crawl4AIBackend(lambda: crawler, retry_policy=POLICY)

        with pytest.raises(CrawlError, match="timeout"):
            asyncio.run(backend.scrape("https://x/"))
        assert crawler.attempts == 3

    def test_exhaustion_of_exceptions_propagates_original(self, stubbed_crawl4ai):
        crawler = FlakyCrawler(["raise", "raise", "raise"])
        backend = Crawl4AIBackend(lambda: crawler, retry_policy=POLICY)

        with pytest.raises(ConnectionError, match="connection reset"):
            asyncio.run(backend.scrape("https://x/"))

    def test_no_policy_means_single_attempt(self, stubbed_crawl4ai):
        crawler = FlakyCrawler(["raise", ok()])
        backend = Crawl4AIBackend(lambda: crawler)

        with pytest.raises(ConnectionError):
            asyncio.run(backend.scrape("https://x/"))
        assert crawler.attempts == 1

    def test_linear_backoff_delays(self, stubbed_crawl4ai, sleeps):
        recorded, fake_sleep = sleeps
        crawler = FlakyCrawler(["raise", "raise", ok()])
        backend = Crawl4AIBackend(
            lambda: crawler,
            retry_policy=RetryPolicy(attempts=3, backoff_seconds=2.0),
            sleeper=fake_sleep,
        )

        asyncio.run(backend.scrape("https://x/"))

        assert recorded == [2.0, 4.0]


class TestCrawlTelemetry:
    def test_failed_pages_recorded_and_successes_returned(self, stubbed_crawl4ai):
        results = [
            ok("https://www.myplannedcare.nhs.uk/a/"),
            fail("https://www.myplannedcare.nhs.uk/b/"),
            ok("https://www.myplannedcare.nhs.uk/c/"),
        ]
        backend = Crawl4AIBackend(lambda: FlakyCrawler([results]), retry_policy=POLICY)

        pages = asyncio.run(backend.crawl("https://www.myplannedcare.nhs.uk/"))

        assert [p.url for p in pages] == [
            "https://www.myplannedcare.nhs.uk/a/",
            "https://www.myplannedcare.nhs.uk/c/",
        ]
        assert backend.last_failed_pages == ("https://www.myplannedcare.nhs.uk/b/",)

    def test_failed_pages_reset_between_crawls(self, stubbed_crawl4ai):
        # One shared crawler so the script is consumed across both calls.
        crawler = FlakyCrawler([[fail()], [ok()]])
        backend = Crawl4AIBackend(lambda: crawler, retry_policy=POLICY)

        asyncio.run(backend.crawl("https://www.myplannedcare.nhs.uk/"))
        assert len(backend.last_failed_pages) == 1

        asyncio.run(backend.crawl("https://www.myplannedcare.nhs.uk/"))
        assert backend.last_failed_pages == ()


class TelemetryFakeBackend:
    """Port-conforming fake that reports failed pages like the real backend."""

    def __init__(self, pages, failed):
        self._pages = pages
        self.last_failed_pages: tuple[str, ...] = ()
        self._failed = failed

    async def scrape(self, url):
        return self._pages[0]

    async def crawl(self, seed, options=None):
        self.last_failed_pages = self._failed
        return self._pages


class TestPipelineTelemetry:
    def test_failed_pages_aggregated_into_result(self, load_fixture):
        page = Page(
            url="https://www.myplannedcare.nhs.uk/seast/royal-berkshire/",
            html=load_fixture("trust_page_royal_berkshire.html"),
        )
        backend = TelemetryFakeBackend([page], ("https://www.myplannedcare.nhs.uk/broken/",))

        result = asyncio.run(
            run_pipeline(
                backend,
                [("https://www.myplannedcare.nhs.uk/seast/royal-berkshire/", "South East")],
                preflight=False,
            )
        )

        assert result.failed_pages == ("https://www.myplannedcare.nhs.uk/broken/",)
        assert len(result.records) == 4  # partial results kept

    def test_backend_without_telemetry_yields_empty(self, load_fixture):
        class BareBackend:
            def __init__(self, pages):
                self._pages = pages

            async def scrape(self, url):
                return self._pages[0]

            async def crawl(self, seed, options=None):
                return self._pages

        page = Page(
            url="https://www.myplannedcare.nhs.uk/seast/royal-berkshire/",
            html=load_fixture("trust_page_royal_berkshire.html"),
        )
        result = asyncio.run(
            run_pipeline(
                BareBackend([page]),
                [("https://www.myplannedcare.nhs.uk/seast/royal-berkshire/", "South East")],
                preflight=False,
            )
        )
        assert result.failed_pages == ()


class TestCliRetryFlags:
    def test_defaults(self):
        from nhs_scraper.cli import parse_args

        args = parse_args([])
        assert args.attempts == 3
        assert args.backoff == 2.0

    def test_custom_values(self):
        from nhs_scraper.cli import parse_args

        args = parse_args(["--attempts", "5", "--backoff", "0.5"])
        assert args.attempts == 5
        assert args.backoff == 0.5
