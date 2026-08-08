"""Unit tests for the immutable domain models (Step 2).

The golden round-trip test is the keystone: it ties the models to the
extraction contract pinned by the Step 1 characterisation baseline, so any
future drift between model serialisation and the agreed schema fails here.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest

from nhs_scraper.domain import CrawlRun, Metric, Page, WaitingTimeRecord

VALID_RECORD = {
    "region": "South East",
    "provider": "Royal Berkshire Hospital NHS Foundation Trust",
    "specialty": "Cardiology",
    "source_url": "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/",
    "metric": "treatment",
    "average_wait_weeks": 8,
    "patients_seen_within_weeks": 16,
    "page_last_updated": "2026-01-26",
}


def make_record(**overrides) -> WaitingTimeRecord:
    return WaitingTimeRecord(**{**VALID_RECORD, **overrides})


class TestWaitingTimeRecord:
    def test_golden_round_trip(self, load_golden):
        for data in load_golden("royal_berkshire_expected.json"):
            record = WaitingTimeRecord.from_dict(data)
            assert record.to_dict() == data

    def test_metric_coerced_to_enum(self):
        assert make_record().metric is Metric.TREATMENT

    def test_page_last_updated_coerced_to_date(self):
        assert make_record().page_last_updated == date(2026, 1, 26)

    @pytest.mark.parametrize(
        "field_name", ["average_wait_weeks", "patients_seen_within_weeks"]
    )
    def test_negative_wait_rejected(self, field_name):
        with pytest.raises(ValueError, match="non-negative"):
            make_record(**{field_name: -1})

    @pytest.mark.parametrize(
        "field_name",
        ["average_wait_weeks", "patients_seen_within_weeks", "page_last_updated"],
    )
    def test_none_values_allowed(self, field_name):
        assert make_record(**{field_name: None}) is not None

    def test_invalid_metric_rejected(self):
        with pytest.raises(ValueError):
            make_record(metric="not_a_metric")

    @pytest.mark.parametrize(
        "url",
        [
            "http://www.myplannedcare.nhs.uk/seast/royal-berkshire/",  # not https
            "https://example.com/seast/royal-berkshire/",  # wrong host
            "https://www.myplannedcare.nhs.uk",  # no path
            "not-a-url",
            "",
        ],
    )
    def test_non_canonical_url_rejected(self, url):
        with pytest.raises(ValueError, match="canonical"):
            make_record(source_url=url)

    @pytest.mark.parametrize("field_name", ["region", "provider", "specialty"])
    def test_blank_strings_rejected(self, field_name):
        with pytest.raises(ValueError, match="non-empty"):
            make_record(**{field_name: "  "})

    def test_malformed_date_string_rejected(self):
        with pytest.raises(ValueError, match="ISO date"):
            make_record(page_last_updated="26/01/2026")

    def test_is_immutable(self):
        record = make_record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.specialty = "Ophthalmology"


class TestPage:
    def test_minimal_construction(self):
        page = Page(url="https://www.myplannedcare.nhs.uk/", html="<html></html>")
        assert page.markdown is None
        assert page.fetched_at.tzinfo is not None

    def test_requires_url(self):
        with pytest.raises(ValueError, match="non-empty"):
            Page(url="", html="<html></html>")

    def test_naive_fetched_at_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            Page(
                url="https://www.myplannedcare.nhs.uk/",
                html="",
                fetched_at=datetime(2026, 1, 1),
            )

    def test_metadata_is_read_only(self):
        page = Page(url="https://www.myplannedcare.nhs.uk/", html="", metadata={"t": "x"})
        with pytest.raises(TypeError):
            page.metadata["t"] = "y"

    def test_is_immutable(self):
        page = Page(url="https://www.myplannedcare.nhs.uk/", html="")
        with pytest.raises(dataclasses.FrozenInstanceError):
            page.html = "changed"


class TestCrawlRun:
    def test_generates_identity_and_timestamp(self):
        run = CrawlRun(seed_url="https://www.myplannedcare.nhs.uk/", backend="fake")
        assert run.run_id
        assert run.started_at.tzinfo is not None
        assert run.started_at <= datetime.now(UTC)

    def test_naive_started_at_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            CrawlRun(
                seed_url="https://www.myplannedcare.nhs.uk/",
                backend="fake",
                started_at=datetime(2026, 1, 1),
            )

    @pytest.mark.parametrize("field_name", ["seed_url", "backend"])
    def test_blank_strings_rejected(self, field_name):
        valid = {"seed_url": "https://www.myplannedcare.nhs.uk/", "backend": "fake"}
        with pytest.raises(ValueError, match="non-empty"):
            CrawlRun(**{**valid, field_name: " "})
