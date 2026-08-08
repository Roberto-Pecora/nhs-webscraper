"""Pure extraction of waiting-time records from crawled trust pages.

No I/O happens here: the function consumes an immutable ``Page`` and
returns validated ``WaitingTimeRecord`` objects. Behaviour is pinned by
the characterisation fixtures and golden dataset.

Expected page shape (My Planned Care trust page):

- ``h1`` — provider (trust) name
- ``section.specialty`` blocks, each with an ``h3`` specialty name
- within a section, ``h4`` headings ("First Outpatient Appointment" /
  "Treatment") each followed by a table whose data row holds
  "N weeks" values for average and 8-in-10 waits
- footer text "Page last updated: DD/MM/YYYY"
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from nhs_scraper.domain import Metric, Page, WaitingTimeRecord

_METRIC_BY_HEADING = {
    "first outpatient appointment": Metric.FIRST_OUTPATIENT_APPOINTMENT,
    "treatment": Metric.TREATMENT,
}

_WEEKS_PATTERN = re.compile(r"(\d+)\s*weeks?", re.IGNORECASE)
_LAST_UPDATED_PATTERN = re.compile(
    r"page last updated:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE
)


def _parse_weeks(cell_text: str) -> int | None:
    """Extract "N weeks" from a table cell; None when absent or n/a."""
    match = _WEEKS_PATTERN.search(cell_text)
    return int(match.group(1)) if match else None


def _parse_page_last_updated(soup: BeautifulSoup) -> date | None:
    match = _LAST_UPDATED_PATTERN.search(soup.get_text(" ", strip=True))
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d/%m/%Y").date()


def _provider_name(soup: BeautifulSoup) -> str | None:
    heading = soup.find("h1")
    return heading.get_text(strip=True) if heading else None


def _table_values(table: Tag) -> tuple[int | None, int | None]:
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None, None
    cells = [c.get_text(strip=True) for c in rows[1].find_all(["td", "th"])]
    average = _parse_weeks(cells[0]) if cells else None
    within = _parse_weeks(cells[1]) if len(cells) > 1 else None
    return average, within


def extract_waiting_times(page: Page, *, region: str) -> list[WaitingTimeRecord]:
    """Extract every waiting-time record present on a trust ``page``.

    Pure: same input, same output, no side effects. Specialties whose data
    is unavailable contribute no records; pages without a provider heading
    are rejected wholesale.
    """
    soup = BeautifulSoup(page.html, "html.parser")
    provider = _provider_name(soup)
    if provider is None:
        return []

    last_updated = _parse_page_last_updated(soup)
    records: list[WaitingTimeRecord] = []

    for section in soup.find_all("section", class_="specialty"):
        specialty_tag = section.find("h3")
        if specialty_tag is None:
            continue
        specialty = specialty_tag.get_text(strip=True)

        for heading in section.find_all("h4"):
            metric = _METRIC_BY_HEADING.get(heading.get_text(strip=True).lower())
            table = heading.find_next_sibling("table")
            if metric is None or table is None:
                continue
            average, within = _table_values(table)
            records.append(
                WaitingTimeRecord(
                    region=region,
                    provider=provider,
                    specialty=specialty,
                    source_url=page.url,
                    metric=metric,
                    average_wait_weeks=average,
                    patients_seen_within_weeks=within,
                    page_last_updated=last_updated,
                )
            )

    return records
