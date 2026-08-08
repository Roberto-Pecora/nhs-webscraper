"""Unit tests for the command-line interface.

``main`` is deliberately not invoked here: it constructs the real
Crawl4AI backend, which belongs to the integration-marked suite.
"""

from __future__ import annotations

import argparse

import pytest

from nhs_scraper.cli import DEFAULT_SEEDS, build_backend, parse_args, parse_seed


class TestParseSeed:
    def test_valid_seed(self):
        assert parse_seed("https://www.myplannedcare.nhs.uk/x/=South East") == (
            "https://www.myplannedcare.nhs.uk/x/",
            "South East",
        )

    def test_region_containing_equals_sign(self):
        url, region = parse_seed("https://x.example/=Region=With=Equals")
        assert region == "Equals"
        assert url == "https://x.example/=Region=With"

    @pytest.mark.parametrize(
        "value", ["no-separator", "=Region Only", "https://x.example/="]
    )
    def test_invalid_seed_rejected(self, value):
        with pytest.raises(argparse.ArgumentTypeError, match="URL=REGION"):
            parse_seed(value)


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.backend == "crawl4ai"
        assert args.seed is None
        assert args.output == "output/my_planned_care.csv"
        assert args.limit == 100
        assert args.max_depth == 2

    def test_repeated_seeds(self):
        args = parse_args(
            [
                "--seed", "https://www.myplannedcare.nhs.uk/a/=South East",
                "--seed", "https://www.myplannedcare.nhs.uk/b/=London",
                "--limit", "25",
            ]
        )
        assert args.seed == [
            ("https://www.myplannedcare.nhs.uk/a/", "South East"),
            ("https://www.myplannedcare.nhs.uk/b/", "London"),
        ]
        assert args.limit == 25

    def test_invalid_seed_exits_with_usage_error(self):
        with pytest.raises(SystemExit):
            parse_args(["--seed", "not-a-seed"])


class TestBuildBackend:
    def test_unknown_backend_rejected(self):
        with pytest.raises(ValueError, match="unknown backend"):
            build_backend("selenium-1999")

    def test_crawl4ai_backend_requires_extra(self):
        # In the unit-test environment crawl4ai is not installed, so
        # construction must fail with the documented remedy.
        with pytest.raises(RuntimeError, match="crawl4ai is not installed"):
            build_backend("crawl4ai")


class TestDefaults:
    def test_default_seed_is_well_formed(self):
        for url, region in DEFAULT_SEEDS:
            assert url.startswith("https://www.myplannedcare.nhs.uk/")
            assert region.strip()
