"""Pre-flight layout probe: catch site drift before any crawl.

The probe runs the extractor's load-bearing structural checks against
one canary page. A structurally valid page that still yields no records
is the subtlest drift (markup present, semantics changed) and is
flagged via the end-to-end signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from nhs_scraper.domain import Page
from nhs_scraper.pipeline.extract import extract_waiting_times


@dataclass(frozen=True)
class LayoutProbeResult:
    ok: bool
    failures: tuple[str, ...]


class LayoutDriftError(RuntimeError):
    """Raised when the canary page fails the layout probe."""

    def __init__(self, url: str, failures: tuple[str, ...] | list[str]):
        self.url = url
        self.failures = tuple(failures)
        super().__init__(f"layout drift at {url}: {'; '.join(self.failures)}")


def probe_layout(page: Page, region: str = "South East") -> LayoutProbeResult:
    """Run structural checks against the current provider-page layout."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page.html, "html.parser")
    failures: list[str] = []

    article = soup.find("article")
    if article is None or article.find("h1") is None:
        failures.append("no <h1> provider heading found")

    if not soup.find_all("div", class_="inner_details_holder"):
        failures.append("no <div class='inner_details_holder'> specialty blocks found")

    captions = {
        (table.find("caption") or BeautifulSoup("", "html.parser")).get_text(strip=True)
        for table in soup.find_all("table", class_="waiting-times-data")
    } - {""}
    if not (captions & {"First Outpatient Appointment", "Treatment"}):
        failures.append("no recognised waiting-times table captions found")

    if not any(
        "Average waiting time" in th.get_text(strip=True)
        for th in soup.find_all("th")
    ):
        failures.append("no waiting-time tables with 'Average waiting time' header found")

    if not any(
        li.get_text(strip=True).startswith("This page was last updated on ")
        for li in soup.find_all("li")
    ):
        failures.append("no 'This page was last updated on ...' footer found")

    if not failures and not extract_waiting_times(page, region):
        failures.append("extractor produced no records from a structurally valid page")

    return LayoutProbeResult(ok=not failures, failures=tuple(failures))
