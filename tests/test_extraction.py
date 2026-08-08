"""Pure-extraction tests, run against the characterisation fixtures.

The keystone test proves the extractor reproduces the golden dataset
exactly; the remaining tests pin the edge-case behaviour agreed in the
domain model: missing data is a state (None / no record), never an error.
The 2026 layout is covered by its own fixture and golden (added when the
site drifted; the baseline fixture is unchanged per the conftest rule).
"""

from __future__ import annotations

from datetime import date

from nhs_scraper.domain import Metric, Page
from nhs_scraper.pipeline.extract import extract_waiting_times

REGION = "South East"
TRUST_URL = "https://www.myplannedcare.nhs.uk/seast/royal-berkshire/"


def make_page(html: str, url: str = TRUST_URL) -> Page:
    return Page(url=url, html=html)


class TestGoldenExtraction:
    def test_fixture_yields_exactly_the_golden_records(self, load_fixture, load_golden):
        page = make_page(load_fixture("trust_page_royal_berkshire.html"))
        records = extract_waiting_times(page, region=REGION)

        expected = load_golden("royal_berkshire_expected.json")
        assert [record.to_dict() for record in records] == expected

    def test_metrics_parse_in_document_order(self, load_fixture):
        page = make_page(load_fixture("trust_page_royal_berkshire.html"))
        records = extract_waiting_times(page, region=REGION)

        assert [r.metric for r in records] == [
            Metric.FIRST_OUTPATIENT_APPOINTMENT,
            Metric.TREATMENT,
            Metric.FIRST_OUTPATIENT_APPOINTMENT,
            Metric.TREATMENT,
        ]

    def test_records_carry_provenance(self, load_fixture):
        page = make_page(load_fixture("trust_page_royal_berkshire.html"))
        records = extract_waiting_times(page, region=REGION)

        for record in records:
            assert record.source_url == TRUST_URL
            assert record.page_last_updated == date(2026, 1, 26)


class TestLayout2026:
    """The 2026 layout: holders + captions + n/a cells + new footer."""

    def test_fixture_yields_exactly_the_2026_golden(self, load_fixture, load_golden):
        page = make_page(load_fixture("trust_page_royal_berkshire_2026.html"))
        records = extract_waiting_times(page, region=REGION)

        expected = load_golden("royal_berkshire_2026_expected.json")
        assert [record.to_dict() for record in records] == expected

    def test_na_cells_yield_null_waits_not_absent_records(self, load_fixture):
        page = make_page(load_fixture("trust_page_royal_berkshire_2026.html"))
        records = extract_waiting_times(page, region=REGION)

        first_outpatient = [
            r for r in records if r.metric is Metric.FIRST_OUTPATIENT_APPOINTMENT
        ]
        assert len(first_outpatient) == 2
        assert all(r.average_wait_weeks is None for r in first_outpatient)

    def test_unavailable_specialty_skipped(self, load_fixture):
        page = make_page(load_fixture("trust_page_royal_berkshire_2026.html"))
        records = extract_waiting_times(page, region=REGION)

        assert "Paediatric Surgery" not in {r.specialty for r in records}

    def test_footer_date_parsed(self, load_fixture):
        page = make_page(load_fixture("trust_page_royal_berkshire_2026.html"))
        records = extract_waiting_times(page, region=REGION)

        assert all(r.page_last_updated == date(2026, 8, 7) for r in records)


class TestEdgeCases:
    def test_unavailable_specialty_yields_no_records(self, load_fixture):
        page = make_page(
            load_fixture("specialty_unavailable.html"),
            url="https://www.myplannedcare.nhs.uk/example/",
        )
        assert extract_waiting_times(page, region=REGION) == []

    def test_page_without_provider_heading_yields_no_records(self):
        html = "<html><body><section class='specialty'><h3>ENT</h3></section></body></html>"
        page = make_page(html, url="https://www.myplannedcare.nhs.uk/x/")
        assert extract_waiting_times(page, region=REGION) == []

    def test_header_only_table_yields_record_with_none_waits(self):
        html = (
            "<html><body><main><h1>Trust X</h1>"
            "<section class='specialty'><h3>ENT</h3><h4>Treatment</h4>"
            "<table><tr><th>Average waiting time</th>"
            "<th>8 in 10 patients seen within</th></tr></table>"
            "</section></main></body></html>"
        )
        page = make_page(html, url="https://www.myplannedcare.nhs.uk/x/")
        (record,) = extract_waiting_times(page, region=REGION)

        assert record.average_wait_weeks is None
        assert record.patients_seen_within_weeks is None

    def test_unknown_metric_heading_is_ignored(self):
        html = (
            "<html><body><main><h1>Trust X</h1>"
            "<section class='specialty'><h3>ENT</h3><h4>Cancelled operations</h4>"
            "<table><tr><th>Count</th></tr><tr><td>3</td></tr></table>"
            "</section></main></body></html>"
        )
        page = make_page(html, url="https://www.myplannedcare.nhs.uk/x/")
        assert extract_waiting_times(page, region=REGION) == []

    def test_na_values_parse_as_none(self):
        html = (
            "<html><body><main><h1>Trust X</h1>"
            "<section class='specialty'><h3>ENT</h3>"
            "<h4>First Outpatient Appointment</h4>"
            "<table><tr><th>Average waiting time</th>"
            "<th>8 in 10 patients seen within</th></tr>"
            "<tr><td>n/a</td><td>6 weeks</td></tr></table>"
            "</section></main></body></html>"
        )
        page = make_page(html, url="https://www.myplannedcare.nhs.uk/x/")
        (record,) = extract_waiting_times(page, region=REGION)

        assert record.average_wait_weeks is None
        assert record.patients_seen_within_weeks == 6
