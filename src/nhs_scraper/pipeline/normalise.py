"""Normalisation: dedupe and order records deterministically.

Crawls can surface the same specialty more than once (overlapping deep
crawl paths), and downstream consumers need stable ordering to diff one
run against the next. Both properties live here, in one pure function.
"""

from __future__ import annotations

from collections.abc import Iterable

from nhs_scraper.domain import Metric, WaitingTimeRecord

_METRIC_ORDER = {
    Metric.FIRST_OUTPATIENT_APPOINTMENT: 0,
    Metric.TREATMENT: 1,
}


def normalise_records(records: Iterable[WaitingTimeRecord]) -> list[WaitingTimeRecord]:
    """Dedupe on identity fields and sort deterministically.

    Identity is (provider, specialty, metric): the first occurrence wins,
    so callers should order sources by trustworthiness. Sort key is
    (region, provider, specialty, metric) with outpatient before treatment.
    """
    seen: set[tuple[str, str, Metric]] = set()
    unique: list[WaitingTimeRecord] = []
    for record in records:
        key = (record.provider, record.specialty, record.metric)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return sorted(
        unique,
        key=lambda r: (r.region, r.provider, r.specialty, _METRIC_ORDER[r.metric]),
    )
