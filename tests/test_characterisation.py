"""Characterisation tests pinning the scraper's observable behaviour.

These tests run entirely offline against captured fixtures. They define the
contract the refactored extractor must honour *before* any production code
is written: the extractor itself lands in step 3, at which point it will be
run against these same fixtures and golden records.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
from bs4 import BeautifulSoup

REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "region": str,
    "provider": str,
    "specialty": str,
    "source_url": str,
    "metric": str,
    "average_wait_weeks": (int, type(None)),
    "patients_seen_within_weeks": (int, type(None)),
    "page_last_updated": (str, type(None)),
}

VALID_METRICS = {"first_outpatient_appointment", "treatment"}
URL_PATTERN = re.compile(r"^https://www\.myplannedcare\.nhs\.uk/[\w\-/]+/$")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TestFixtures:
    """The captured fixtures must remain faithful to the live site structure."""

    def test_trust_page_fixture_is_well_formed(self, load_fixture):
        soup = BeautifulSoup(load_fixture("trust_page_royal_berkshire.html"), "html.parser")

        heading = soup.find("h1")
        assert heading is not None
        assert "Royal Berkshire" in heading.get_text()
        assert len(soup.find_all("h3")) >= 2, "expected multiple specialty sections"

    def test_unavailable_specialty_fixture_has_no_data_tables(self, load_fixture):
        soup = BeautifulSoup(load_fixture("specialty_unavailable.html"), "html.parser")

        assert "currently unavailable" in soup.get_text().lower()
        assert soup.find("table") is None


class TestGoldenSchema:
    """The golden dataset is the extraction contract for later steps."""

    @pytest.fixture()
    def records(self, load_golden):
        return load_golden("royal_berkshire_expected.json")

    def test_golden_file_matches_fixture_coverage(self, records):
        # Two specialties with data, two metrics each; the unavailable
        # specialty contributes no records.
        assert len(records) == 4
        assert {r["specialty"] for r in records} == {"Breast Surgery", "Cardiology"}

    def test_required_fields_present_and_typed(self, records):
        for record in records:
            for field, expected_type in REQUIRED_FIELDS.items():
                assert field in record, f"missing field {field!r}"
                assert isinstance(record[field], expected_type), (
                    f"{field!r} has wrong type: {type(record[field]).__name__}"
                )

    def test_metric_enum(self, records):
        for record in records:
            assert record["metric"] in VALID_METRICS

    def test_waiting_times_non_negative(self, records):
        for record in records:
            for field in ("average_wait_weeks", "patients_seen_within_weeks"):
                value = record[field]
                assert value is None or value >= 0

    def test_source_urls_are_canonical(self, records):
        for record in records:
            assert URL_PATTERN.match(record["source_url"]), record["source_url"]

    def test_page_last_updated_is_iso_or_null(self, records):
        for record in records:
            value = record["page_last_updated"]
            if value is not None:
                assert ISO_DATE_PATTERN.match(value)
                date.fromisoformat(value)  # raises on invalid calendar dates
