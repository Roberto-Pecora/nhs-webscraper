"""Immutable domain models for the waiting-time extraction pipeline.

Models are frozen dataclasses validated in ``__post_init__``. They carry no
I/O behaviour: crawling, parsing and persistence live in separate modules
and operate on these objects.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Metric(StrEnum):
    """Waiting-time metrics published per specialty."""

    FIRST_OUTPATIENT_APPOINTMENT = "first_outpatient_appointment"
    TREATMENT = "treatment"


_CANONICAL_URL = re.compile(r"^https://www\.myplannedcare\.nhs\.uk/[\w\-/]+/$")


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_non_negative(value: int | None, field_name: str) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be non-negative, got {value}")


def _coerce_date(value: date | str | None, field_name: str) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be an ISO date string, got {value!r}"
            ) from exc
    raise TypeError(f"{field_name} must be a date, ISO string or None")


def _require_tz_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class Page:
    """An immutable snapshot of a crawled page.

    ``metadata`` is copied into a read-only mapping so a frozen ``Page``
    cannot be mutated through it. ``fetched_at`` must be timezone-aware so
    crawl provenance is unambiguous across locales and DST boundaries.
    """

    url: str
    html: str
    markdown: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        _require_non_empty(self.url, "url")
        _require_tz_aware(self.fetched_at, "fetched_at")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class WaitingTimeRecord:
    """A single validated waiting-time observation.

    Accepts ``metric`` as a ``Metric`` member or its string value, and
    ``page_last_updated`` as a ``date`` or ISO string; both are normalised
    in ``__post_init__`` so downstream code sees one canonical form.
    """

    region: str
    provider: str
    specialty: str
    source_url: str
    metric: Metric | str
    average_wait_weeks: int | None = None
    patients_seen_within_weeks: int | None = None
    page_last_updated: date | str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.metric, str):
            # Metric(...) raises ValueError for values outside the enum.
            object.__setattr__(self, "metric", Metric(self.metric))
        object.__setattr__(
            self,
            "page_last_updated",
            _coerce_date(self.page_last_updated, "page_last_updated"),
        )
        _require_non_empty(self.region, "region")
        _require_non_empty(self.provider, "provider")
        _require_non_empty(self.specialty, "specialty")
        if not _CANONICAL_URL.match(self.source_url):
            raise ValueError(
                "source_url must be a canonical My Planned Care URL, "
                f"got {self.source_url!r}"
            )
        _require_non_negative(self.average_wait_weeks, "average_wait_weeks")
        _require_non_negative(
            self.patients_seen_within_weeks, "patients_seen_within_weeks"
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WaitingTimeRecord:
        """Build a record from a plain mapping (e.g. a golden JSON entry)."""
        return cls(**dict(data))

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the golden-schema shape defined in Step 1."""
        return {
            "region": self.region,
            "provider": self.provider,
            "specialty": self.specialty,
            "source_url": self.source_url,
            "metric": str(self.metric),
            "average_wait_weeks": self.average_wait_weeks,
            "patients_seen_within_weeks": self.patients_seen_within_weeks,
            "page_last_updated": (
                self.page_last_updated.isoformat() if self.page_last_updated else None
            ),
        }


@dataclass(frozen=True)
class CrawlRun:
    """Provenance for one execution of the pipeline."""

    seed_url: str
    backend: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        _require_non_empty(self.seed_url, "seed_url")
        _require_non_empty(self.backend, "backend")
        _require_tz_aware(self.started_at, "started_at")
