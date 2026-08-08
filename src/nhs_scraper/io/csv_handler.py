"""CSV persistence for waiting-time records.

The column order is fixed and versioned with the golden schema: changing
it is a breaking change for downstream consumers.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from nhs_scraper.domain import WaitingTimeRecord

COLUMNS = [
    "region",
    "provider",
    "specialty",
    "source_url",
    "metric",
    "average_wait_weeks",
    "patients_seen_within_weeks",
    "page_last_updated",
]

_INT_COLUMNS = ("average_wait_weeks", "patients_seen_within_weeks")


def write_records_csv(
    records: Iterable[WaitingTimeRecord], path: str | Path
) -> Path:
    """Write records to ``path`` in the canonical column order.

    Week columns use pandas' nullable Int64 so values serialise as plain
    integers (``8``) and None as an empty cell — never ``8.0``. Empty
    input yields a header-only file. Parent directories are created.
    """
    path = Path(path)
    frame = pd.DataFrame([record.to_dict() for record in records], columns=COLUMNS)
    frame = frame.astype({column: "Int64" for column in _INT_COLUMNS})
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def _to_int(value: str | None) -> int | None:
    """Parse a week count; tolerates legacy float formatting (``8.0``)."""
    value = (value or "").strip()
    if not value:
        return None
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"expected a whole number of weeks, got {value!r}")
    return int(number)


def read_records_csv(path: str | Path) -> list[WaitingTimeRecord]:
    """Read a CSV written by :func:`write_records_csv` back into records.

    The header must match the canonical column order exactly — a mismatch
    means the file did not come from this pipeline (or the schema moved),
    which is worth failing loudly. Empty cells read back as None.
    """
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise ValueError(
                f"unexpected CSV header {reader.fieldnames}; expected {COLUMNS}"
            )
        return [
            WaitingTimeRecord.from_dict(
                {
                    "region": row["region"],
                    "provider": row["provider"],
                    "specialty": row["specialty"],
                    "source_url": row["source_url"],
                    "metric": row["metric"],
                    "average_wait_weeks": _to_int(row["average_wait_weeks"]),
                    "patients_seen_within_weeks": _to_int(
                        row["patients_seen_within_weeks"]
                    ),
                    "page_last_updated": row["page_last_updated"].strip() or None,
                }
            )
            for row in reader
        ]
