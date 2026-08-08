"""Extract waiting-time records from a provider page.

The extractor is a pure function over the page's HTML. It depends on
the load-bearing signals the preflight probe checks; when those drift,
the probe aborts before a crawl rather than yielding a silently empty
result here.

Current layout (2026): each specialty is a ``div.inner_details_holder``
containing an ``h3.nhsblue-text0`` heading ("Specialty - Waiting
Times") and two ``table.waiting-times-data`` tables — one captioned
"First Outpatient Appointment", one "Treatment". Cells may contain
``<em>n/a</em>`` (metric not delivered); those rows are skipped, as
are specialties whose holder has no table ("currently unavailable").
"""

from __future__ import annotations

from nhs_scraper.domain import Page, WaitingTimeRecord

_NA_VALUES = {"n/a", "na", ""}


def _text(element) -> str:
    return element.get_text(strip=True) if element else ""


def _metric_from_caption(caption: str) -> str:
    return "first_outpatient" if "First Outpatient" in caption else "treatment"


def _cell_value(td_text: str) -> str | None:
    return None if td_text.lower() in _NA_VALUES else td_text


def extract_waiting_times(page: Page, region: str) -> list[WaitingTimeRecord]:
    """Extract one record per (specialty, metric) with at least one wait.

    Returns an empty list when the page yields nothing — the caller's
    contract treats absence as an extraction failure signal, not an
    error.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page.html, "html.parser")
    article = soup.find("article")
    provider = _text(article.find("h1")) if article else ""
    last_updated = next(
        (
            _text(li).removeprefix("This page was last updated on ").rstrip(".")
            for li in soup.find_all("li")
            if _text(li).startswith("This page was last updated on ")
        ),
        None,
    )

    records: list[WaitingTimeRecord] = []
    for holder in soup.find_all("div", class_="inner_details_holder"):
        heading = holder.find("h3", class_="nhsblue-text0")
        if heading is None:
            continue
        specialty = _text(heading).removesuffix(" - Waiting Times")

        for table in holder.find_all("table", class_="waiting-times-data"):
            caption = _text(table.find("caption"))
            if not caption:
                continue
            metric = _metric_from_caption(caption)
            average = p80 = None
            for row in table.find_all("tr"):
                th, td = row.find("th"), row.find("td")
                if th is None or td is None:
                    continue
                label, value = _text(th), _cell_value(_text(td))
                if "Average waiting time" in label:
                    average = value
                elif "8 in 10 patients" in label:
                    p80 = value
            if average is None and p80 is None:
                continue  # whole metric n/a for this specialty
            records.append(
                WaitingTimeRecord(
                    provider=provider,
                    specialty=specialty,
                    metric=metric,
                    average_wait=average,
                    percentile_80=p80,
                    region=region,
                    source_url=page.url,
                    last_updated=last_updated,
                )
            )
    return records
