"""Pure extraction of waiting-time records from crawled trust pages.

No I/O happens here: the function consumes an immutable ``Page`` and
returns validated ``WaitingTimeRecord`` objects. Behaviour is pinned by
the characterisation fixtures and golden dataset.

Two layouts are supported. The legacy layout (pre-2026, kept as the
characterisation baseline) uses ``section.specialty`` blocks with ``h4``
metric headings. The 2026 layout uses ``div.inner_details_holder`` blocks
with table ``<caption>`` metric labels and ``n/a`` cells; its footer
reads "This page was last updated on D Month YYYY". New-layout extraction
is tried first; a page with no 2026 holders falls back to legacy.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from nhs_scraper.domain import Metric, Page, WaitingTimeRecord

_METRIC_BY_LABEL = {
    "first outpatient appointment": Metric.FIRST_OUTPATIENT_APPOINTMENT,
    "treatment": Metric.TREATMENT,
}

_WEEKS_PATTERN = re.compile(r"(\d+)\s*weeks?", re.IGNORECASE)
_LEGACY_FOOTER = re.compile(r"page last updated:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_2026_FOOTER = re.compile(
    r"this page was last updated on\s+(\d{1,2}\s+\w+\s+\d{4})", re.IGNORECASE
)


def _parse_weeks(cell_text: str) -> int | None:
    """Extract "N weeks" from a table cell; None when absent or n/a."""
    match = _WEEKS_PATTERN.search(cell_text)
    return int(match.group(1)) if match else None


def _parse_page_last_updated(soup: BeautifulSoup) -> date | None:
    text = soup.get_text(" ", strip=True)
    if match := _LEGACY_FOOTER.search(text):
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()
    if match := _2026_FOOTER.search(text):
        return datetime.strptime(match.group(1), "%d %B %Y").date()
    return None


def _provider_name(soup: BeautifulSoup) -> str | None:
    heading = soup.find("h1")
    return heading.get_text(strip=True) if heading else None


def _make_record(
    *, region, provider, specialty, source_url, metric, average, within, updated
) -> WaitingTimeRecord:
    return WaitingTimeRecord(
        region=region,
        provider=provider,
        specialty=specialty,
        source_url=source_url,
        metric=metric,
        average_wait_weeks=average,
        patients_seen_within_weeks=within,
        page_last_updated=updated,
    )


def _extract_2026(
    soup: BeautifulSoup, *, region, provider, source_url, updated
) -> list[WaitingTimeRecord]:
    """Extract from the 2026 ``div.inner_details_holder`` layout."""
    records: list[WaitingTimeRecord] = []
    for holder in soup.find_all("div", class_="inner_details_holder"):
        heading = holder.find("h3", class_="nhsblue-text0")
        if heading is None:
            continue
        specialty = heading.get_text(strip=True).removesuffix(" - Waiting Times")

        for table in holder.find_all("table", class_="waiting-times-data"):
            caption = table.find("caption")
            metric = (
                _METRIC_BY_LABEL.get(caption.get_text(strip=True).lower())
                if caption
                else None
            )
            if metric is None:
                continue
            average = within = None
            for row in table.find_all("tr"):
                th, td = row.find("th"), row.find("td")
                if th is None or td is None:
                    continue
                label = th.get_text(strip=True).lower()
                value = td.get_text(strip=True)
                if "average waiting time" in label:
                    average = _parse_weeks(value)
                elif "8 in 10 patients" in label:
                    within = _parse_weeks(value)
            records.append(
                _make_record(
                    region=region,
                    provider=provider,
                    specialty=specialty,
                    source_url=source_url,
                    metric=metric,
                    average=average,
                    within=within,
                    updated=updated,
                )
            )
    return records


def _extract_legacy(
    soup: BeautifulSoup, *, region, provider, source_url, updated
) -> list[WaitingTimeRecord]:
    """Extract from the legacy ``section.specialty`` layout."""
    records: list[WaitingTimeRecord] = []
    for section in soup.find_all("section", class_="specialty"):
        specialty_tag = section.find("h3")
        if specialty_tag is None:
            continue
        specialty = specialty_tag.get_text(strip=True)

        for heading in section.find_all("h4"):
            metric = _METRIC_BY_LABEL.get(heading.get_text(strip=True).lower())
            table = heading.find_next_sibling("table")
            if metric is None or table is None:
                continue
            rows = table.find_all("tr")
            cells = (
                [c.get_text(strip=True) for c in rows[1].find_all(["td", "th"])]
                if len(rows) > 1
                else []
            )
            average = _parse_weeks(cells[0]) if cells else None
            within = _parse_weeks(cells[1]) if len(cells) > 1 else None
            records.append(
                _make_record(
                    region=region,
                    provider=provider,
                    specialty=specialty,
                    source_url=source_url,
                    metric=metric,
                    average=average,
                    within=within,
                    updated=updated,
                )
            )
    return records


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

    updated = _parse_page_last_updated(soup)
    context = dict(
        region=region,
        provider=provider,
        source_url=page.url,
        updated=updated,
    )
    return _extract_2026(soup, **context) or _extract_legacy(soup, **context)
