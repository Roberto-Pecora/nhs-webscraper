"""Pre-flight layout probe: detect site structure drift before crawling.

Runs the structural signals the extractor depends on against a single
canary page, then the extractor itself end-to-end. Both the legacy and
the 2026 layouts are recognised; a page matching neither fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from nhs_scraper.domain import Page
from nhs_scraper.pipeline.extract import extract_waiting_times

_KNOWN_METRIC_LABELS = {"first outpatient appointment", "treatment"}
_LEGACY_FOOTER = re.compile(r"page last updated:\s*\d{2}/\d{2}/\d{4}", re.IGNORECASE)
_2026_FOOTER = re.compile(
    r"this page was last updated on\s+\d{1,2}\s+\w+\s+\d{4}", re.IGNORECASE
)


@dataclass(frozen=True)
class LayoutProbeResult:
    """Outcome of probing one canary page."""

    ok: bool
    failures: tuple[str, ...] = ()


class LayoutDriftError(RuntimeError):
    """Raised when the canary page no longer matches any known layout."""

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

    if not (
        soup.find_all("section", class_="specialty")
        or soup.find_all("div", class_="inner_details_holder")
    ):
        failures.append("no recognised specialty blocks found")

    headings = {h.get_text(strip=True).lower() for h in soup.find_all("h4")}
    captions = {
        caption.get_text(strip=True).lower()
        for table in soup.find_all("table")
        if (caption := table.find("caption")) is not None
    }
    if not (headings | captions) & _KNOWN_METRIC_LABELS:
        failures.append("no recognised metric labels found")

    if not any(
        "average waiting time" in th.get_text(strip=True).lower()
        for th in soup.find_all("th")
    ):
        failures.append("no waiting-time tables with 'Average waiting time' header found")

    text = soup.get_text(" ", strip=True)
    if not (_LEGACY_FOOTER.search(text) or _2026_FOOTER.search(text)):
        failures.append("no recognised last-updated footer found")

    return failures


def probe_layout(page: Page) -> LayoutProbeResult:
    """Probe one canary page for a layout the extractor understands.

    Structural checks run first; only when they all pass is the extractor
    run end-to-end — a structurally valid page that still yields no
    records is the subtlest drift of all.
    """
    failures = _structural_failures(page)
    if not failures and not extract_waiting_times(page, region="_probe"):
        failures.append("extractor produced no records from a structurally valid page")
    return LayoutProbeResult(ok=not failures, failures=tuple(failures))
