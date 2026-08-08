"""Unit tests for record normalisation: dedupe and deterministic order."""

from __future__ import annotations

from nhs_scraper.domain import Metric, WaitingTimeRecord
from nhs_scraper.pipeline.normalise import normalise_records

BASE = {
    "region": "South East",
    "source_url": "https://www.myplannedcare.nhs.uk/x/",
}


def rec(provider, specialty, metric, average=None, region="South East"):
    return WaitingTimeRecord(
        region=region,
        provider=provider,
        specialty=specialty,
        metric=metric,
        average_wait_weeks=average,
        source_url=BASE["source_url"],
    )


class TestDedupe:
    def test_duplicate_identity_first_occurrence_wins(self):
        first = rec("Trust B", "Cardiology", Metric.TREATMENT, average=8)
        duplicate = rec("Trust B", "Cardiology", Metric.TREATMENT, average=99)

        result = normalise_records([first, duplicate])

        assert result == [first]

    def test_distinct_metrics_are_not_duplicates(self):
        foa = rec("Trust B", "Cardiology", Metric.FIRST_OUTPATIENT_APPOINTMENT)
        treatment = rec("Trust B", "Cardiology", Metric.TREATMENT)

        assert len(normalise_records([foa, treatment])) == 2

    def test_same_provider_under_two_regions_is_not_deduped(self):
        # Regression for the multi-seed aggregation failure: region is
        # part of the dedupe identity.
        south_east = rec("Trust B", "Cardiology", Metric.TREATMENT, region="South East")
        london = rec("Trust B", "Cardiology", Metric.TREATMENT, region="London")

        result = normalise_records([south_east, london])

        assert len(result) == 2
        assert {r.region for r in result} == {"South East", "London"}

    def test_empty_input(self):
        assert normalise_records([]) == []


class TestOrdering:
    def test_sorted_by_region_provider_specialty_metric(self):
        treatment = rec("Trust B", "Cardiology", Metric.TREATMENT)
        foa = rec("Trust B", "Cardiology", Metric.FIRST_OUTPATIENT_APPOINTMENT)
        ent = rec("Trust A", "ENT", Metric.TREATMENT)
        london = rec("Trust Z", "ENT", Metric.TREATMENT, region="London")

        result = normalise_records([london, treatment, foa, ent])

        assert [(r.provider, r.specialty, r.metric) for r in result] == [
            ("Trust Z", "ENT", Metric.TREATMENT),  # London sorts before South East
            ("Trust A", "ENT", Metric.TREATMENT),
            ("Trust B", "Cardiology", Metric.FIRST_OUTPATIENT_APPOINTMENT),
            ("Trust B", "Cardiology", Metric.TREATMENT),
        ]

    def test_outpatient_sorts_before_treatment(self):
        treatment = rec("Trust", "ENT", Metric.TREATMENT)
        foa = rec("Trust", "ENT", Metric.FIRST_OUTPATIENT_APPOINTMENT)

        result = normalise_records([treatment, foa])

        assert [r.metric for r in result] == [
            Metric.FIRST_OUTPATIENT_APPOINTMENT,
            Metric.TREATMENT,
        ]
