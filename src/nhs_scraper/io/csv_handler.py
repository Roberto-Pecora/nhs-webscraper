"""CSV persistence for waiting-time records.

The column order is fixed and versioned with the golden schema: changing
it is a breaking change for downstream consumers.
"""

from __future__ import annotations

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


def write_records_csv(
    records: Iterable[WaitingTimeRecord], path: str | Path
) -> Path:
    """Write records to ``path`` in the canonical column order.

    Empty input yields a header-only file (a valid, explicit "no data"
    artefact). Parent directories are created as needed. None values are
    written as empty cells by pandas.
    """
    path = Path(path)
    frame = pd.DataFrame([record.to_dict() for record in records], columns=COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    return path
