"""Pre-flight layout probe: detect site structure drift before crawling.

Runs the structural signals the extractor depends on against a single
canary page, then the extractor itself end-to-end. Far cheaper and more
diagnosable than discovering an empty CSV after a full crawl.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from nhs_scraper.domain import Page
from nhs_scraper.pipeline.extract import extract_waiting_times

_KNOWN_METRIC_HEADINGS = {"first outpatient appointment", "treatment"}
_LAST_UPDATED_PATTERN = re.compile(
    r"page last updated:\s*\d{2}/\d{2}/\d{4}", re.IGNORECASE
)


@dataclass(frozen=True)
class LayoutProbeResult:
    """Outcome of probing one canary page."""

    ok: bool
    failures: tuple[str, ...] = ()


class LayoutDriftError(RuntimeError):
    """Raised when the canary page no longer matches the expected layout."""

    def __init__(self, url: str, failures: tuple[str, ...]) -> None:
        self.url = url
        self.failures = failures
        super().__init__(f"layout probe failed for {url}: " + "; ".join(failures))


def _structural_failures(page: Page) -> list[str]:
    """Check each load-bearing structural signal, collecting all failures."""
    soup = BeautifulSoup(page.html, "html.parser")
    failures: list[str] = []

    if not soup.find("h1"):
        failures.append("no <h1> provider heading found")
    if not soup.find_all("section", class_="specialty"):
        failures.append("no <section class='specialty'> blocks found")

    headings = {h.get_text(strip=True).lower() for h in soup.find_all("h4")}
    if not headings & _KNOWN_METRIC_HEADINGS:
        failures.append("no recognised metric headings (h4) found")

    has_waiting_table = any(
        (row := table.find("tr")) is not None
        and "average waiting time" in row.get_text(strip=True).lower()
        for table in soup.find_all("table")
    )
    if not has_waiting_table:
        failures.append("no waiting-time tables with 'Average waiting time' header found")

    if not _LAST_UPDATED_PATTERN.search(soup.get_text(" ", strip=True)):
        failures.append("no 'Page last updated: DD/MM/YYYY' footer found")

    return failures


def probe_layout(page: Page) -> LayoutProbeResult:
    """Probe one canary page for the layout the extractor depends on.

    Structural checks run first; only when they all pass is the extractor
    run end-to-end — a structurally valid page that still yields no
    records is the subtlest drift of all.
    """
    failures = _structural_failures(page)
    if not failures and not extract_waiting_times(page, region="_probe"):
        failures.append("extractor produced no records from a structurally valid page")
    return LayoutProbeResult(ok=not failures, failures=tuple(failures))
