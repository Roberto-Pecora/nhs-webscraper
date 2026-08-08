"""Seed discovery: enumerate region and trust URLs from the live site.

The My Planned Care site is organised as ``/<region-slug>/<trust>/``.
Discovery scrapes the homepage once for region links, then each region
page once for trust links, producing the ``(url, region)`` seed pairs
``run_pipeline`` already consumes — so a full-site run needs no
hand-maintained seed list.

Both parsers are pure functions over HTML strings; only
``discover_seeds`` touches the backend.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from nhs_scraper.ports import CrawlBackend

#: Default entry point for discovery.
BASE_URL = "https://www.myplannedcare.nhs.uk/"

#: Region path slugs -> display names threaded into extracted records.
#: An allowlist (not "any single path segment") keeps utility pages like
#: /find-my-hospital/ out of the region set. Unknown slugs fall back to
#: the slug itself as the region name, so a newly added region still
#: works — just with an unpretty label until the map is updated.
REGION_SLUG_TO_NAME: dict[str, str] = {
    "east": "East of England",
    "london": "London",
    "midlands": "Midlands",
    "neast": "North East",
    "nwest": "North West",
    "seast": "South East",
    "swest": "South West",
}


def _normalise(url: str) -> str:
    """Normalise to a trailing-slash URL so dedupe and prefix checks hold."""
    return url if url.endswith("/") else url + "/"


def _path_segments(url: str) -> list[str]:
    return [part for part in urlparse(url).path.split("/") if part]


def _iter_urls(html: str, base_url: str):
    """Yield absolute, same-host, normalised URLs from every anchor."""
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        url = _normalise(urljoin(base_url, anchor["href"]))
        if urlparse(url).netloc == urlparse(base_url).netloc:
            yield url


def discover_region_urls(html: str, base_url: str = BASE_URL) -> list[str]:
    """Extract region page URLs from the homepage, in document order."""
    urls: list[str] = []
    seen: set[str] = set()
    for url in _iter_urls(html, base_url):
        parts = _path_segments(url)
        if len(parts) == 1 and parts[0] in REGION_SLUG_TO_NAME and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def discover_trust_seeds(
    region_url: str, html: str, base_url: str = BASE_URL
) -> list[tuple[str, str]]:
    """Extract ``(trust_url, region)`` seeds from a region page.

    A trust link is exactly one path level below the region URL — this
    excludes self links, specialty pages (two levels down) and links to
    other regions' trusts.
    """
    region_url = _normalise(region_url)
    slug = _path_segments(region_url)[0]
    region_name = REGION_SLUG_TO_NAME.get(slug, slug)
    seeds: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url in _iter_urls(html, region_url):
        if (
            url != region_url
            and url.startswith(region_url)
            and len(_path_segments(url)) == 2
            and url not in seen
        ):
            seen.add(url)
            seeds.append((url, region_name))
    return seeds


async def discover_seeds(
    backend: CrawlBackend, base_url: str = BASE_URL
) -> list[tuple[str, str]]:
    """Scrape the homepage and region pages to build the full seed list.

    Raises ``ValueError`` when discovery finds nothing — a silent empty
    seed list would produce a silently empty CSV, the failure mode the
    preflight probe exists to prevent.
    """
    homepage = await backend.scrape(base_url)
    region_urls = discover_region_urls(homepage.html, base_url)
    if not region_urls:
        raise ValueError(f"no region links discovered from {base_url}")

    seeds: list[tuple[str, str]] = []
    for region_url in region_urls:
        region_page = await backend.scrape(region_url)
        seeds.extend(discover_trust_seeds(region_url, region_page.html, base_url))
    if not seeds:
        raise ValueError("region pages yielded no trust links")
    return seeds
