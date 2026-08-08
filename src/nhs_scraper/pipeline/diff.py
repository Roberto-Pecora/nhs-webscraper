"""Row-level parity diff between two record sets.

Keys records on the same identity as ``normalise_records`` —
(region, provider, specialty, metric) — so a diff between two pipeline
runs (or two backends) classifies every key as added, removed, changed
or unchanged. Changed entries carry field-level detail.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from nhs_scraper.domain import WaitingTimeRecord

IDENTITY_FIELDS = ("region", "provider", "specialty", "metric")
COMPARED_FIELDS = (
    "source_url",
    "average_wait_weeks",
    "patients_seen_within_weeks",
    "page_last_updated",
)

ChangeKind = Literal["added", "removed", "changed"]


def _key(record: WaitingTimeRecord) -> tuple:
    return tuple(getattr(record, field_name) for field_name in IDENTITY_FIELDS)


@dataclass(frozen=True)
class RecordChange:
    """One keyed difference between two record sets."""

    kind: ChangeKind
    key: tuple
    old: WaitingTimeRecord | None
    new: WaitingTimeRecord | None
    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParityReport:
    """The full diff between two record sets."""

    added: tuple[RecordChange, ...] = ()
    removed: tuple[RecordChange, ...] = ()
    changed: tuple[RecordChange, ...] = ()
    unchanged_count: int = 0

    @property
    def is_identical(self) -> bool:
        return not (self.added or self.removed or self.changed)

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)

    def summary(self) -> str:
        return (
            f"{self.total_changes} change(s): "
            f"+{len(self.added)} added, -{len(self.removed)} removed, "
            f"~{len(self.changed)} changed, ={self.unchanged_count} unchanged"
        )


def diff_records(
    old: Iterable[WaitingTimeRecord], new: Iterable[WaitingTimeRecord]
) -> ParityReport:
    """Classify every identity key as added, removed, changed or unchanged.

    Pure and deterministic: output ordering follows the sorted keys, so
    reports are stable across runs. A ``None`` -> value transition counts
    as a change on that field.
    """
    old_by_key = {_key(record): record for record in old}
    new_by_key = {_key(record): record for record in new}

    added = tuple(
        RecordChange("added", key, None, new_by_key[key])
        for key in sorted(new_by_key)
        if key not in old_by_key
    )
    removed = tuple(
        RecordChange("removed", key, old_by_key[key], None)
        for key in sorted(old_by_key)
        if key not in new_by_key
    )

    changed: list[RecordChange] = []
    unchanged = 0
    for key in sorted(old_by_key.keys() & new_by_key.keys()):
        old_record, new_record = old_by_key[key], new_by_key[key]
        fields = tuple(
            field_name
            for field_name in COMPARED_FIELDS
            if getattr(old_record, field_name) != getattr(new_record, field_name)
        )
        if fields:
            changed.append(RecordChange("changed", key, old_record, new_record, fields))
        else:
            unchanged += 1

    return ParityReport(added, removed, tuple(changed), unchanged)


def format_change(change: RecordChange) -> str:
    """Render one change as a single human-readable line."""
    label = " / ".join(str(part) for part in change.key)
    if change.kind == "added":
        return f"+ {label}"
    if change.kind == "removed":
        return f"- {label}"
    details = ", ".join(
        f"{field_name}: {getattr(change.old, field_name)} -> {getattr(change.new, field_name)}"
        for field_name in change.changed_fields
    )
    return f"~ {label} ({details})"
