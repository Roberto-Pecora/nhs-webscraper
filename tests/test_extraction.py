"""Offline tests for the extractor against the fixture and edge cases."""

from __future__ import annotations

from nhs_scraper.domain import Page
from nhs_scraper.pipeline.extract import extract_waiting_times

TRUST_URL = "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/"


def page(html: str) -> Page:
    return Page(url=TRUST_URL, html=html)


class TestGoldenExtraction:
    def test_fixture_yields_golden_records(self, load_fixture, load_golden):
        records = extract_waiting_times(
            page(load_fixture("trust_page_royal_berkshire.html")), region="South East"
        )

        assert [r.to_dict() for r in records] == load_golden("royal_berkshire_expected.json")

    def test_first_outpatient_na_rows_skipped(self, load_fixture):
        records = extract_waiting_times(
            page(load_fixture("trust_page_royal_berkshire.html")), region="South East"
        )

        assert all(r.metric == "treatment" for r in records)
        assert len(records) == 2  # Breast + Cardiology; first-outpatient n/a

    def test_unavailable_specialty_skipped(self, load_fixture):
        records = extract_waiting_times(
            page(load_fixture("trust_page_royal_berkshire.html")), region="South East"
        )

        assert "Paediatric Surgery" not in {r.specialty for r in records}

    def test_footer_date_extracted(self, load_fixture):
        records = extract_waiting_times(
            page(load_fixture("trust_page_royal_berkshire.html")), region="South East"
        )

        assert all(r.last_updated == "7 August 2026" for r in records)


class TestEdgeCases:
    def test_empty_page_yields_nothing(self):
        assert extract_waiting_times(page("<html><body></body></html>"), "South East") == []

    def test_metric_from_caption(self):
        html = (
            "<article><header><h1>Trust X</h1></header>"
            "<div class='inner_details_holder'><div>"
            "<h3 class='nhsblue-text0'>ENT - Waiting Times</h3>"
            "<table class='waiting-times-data'><caption>First Outpatient Appointment</caption>"
            "<tr><th>Average waiting time for first outpatient appointment</th><td>5 weeks</td></tr>"
            "<tr><th>8 in 10 patients will be seen within</th><td>9 weeks</td></tr>"
            "</table></div></div></article>"
        )
        records = extract_waiting_times(page(html), "South East")

        assert len(records) == 1
        assert records[0].metric == "first_outpatient"
        assert records[0].average_wait == "5 weeks"
        assert records[0].percentile_80 == "9 weeks"
