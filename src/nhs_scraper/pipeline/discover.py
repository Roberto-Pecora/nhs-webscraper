"""Seed discovery: enumerate region and trust URLs from the live site.

The My Planned Care site is organised as ``/<region-slug>/<trust>/``.
Discovery scrapes the homepage once for region links, then each region
page once for trust links, producing the ``(url, region)`` seed pairs
``run_pipeline`` already consumes — so a full-site run needs no
hand-maintained seed list.

Region pages list both genuine NHS trusts and independent/private
providers (Nuffield, Spire, Spamedica, Circle, Ramsay, CHEC, Optegra,
Newmedica, ACES, Practice Plus Group, ...) as sibling links one path
level below the region URL, with no DOM-level distinction between the
two groups. ``discover_trust_seeds`` filters to NHS trusts only, using
the one signal verified with zero exceptions against the live site: a
genuine trust's visible link text always ends in "NHS Trust" or "NHS
Foundation Trust"; independent providers instead follow a "Location -
Brand" pattern. Skipping independent providers keeps a full-site crawl
from fetching several times more pages than the NHS waiting-time data
actually requires.

Both parsers are pure functions over HTML strings; only
``discover_seeds`` touches the backend.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from nhs_scraper.ports import CrawlBackend

logger = logging.getLogger(__name__)

#: Default entry point for discovery.
BASE_URL = "https://www.myplannedcare.nhs.uk/"

#: Region path slugs -> display names threaded into extracted records,
#: verified against the live site (e.g. /ney/north-cumbria/).
#: An allowlist (not "any single path segment") keeps utility pages like
#: /find-my-hospital/ out of the region set. Unknown slugs fall back to
#: the slug itself as the region name, so a newly added region still
#: works — just with an unpretty label until the map is updated.
REGION_SLUG_TO_NAME: dict[str, str] = {
    "east": "East of England",
    "london": "London",
    "mids": "Midlands",
    "ney": "North East and Yorkshire",
    "nwest": "North West",
    "seast": "South East",
    "swest": "South West",
}

#: Visible link-text suffixes that mark a genuine NHS trust, verified with
#: zero exceptions against the live South East and London region pages.
#: Independent/private providers (Nuffield, Spire, Spamedica, Circle,
#: Ramsay, CHEC, Optegra, Newmedica, ACES, Practice Plus Group, ...) use a
#: "Location - Brand" link text instead and never match this suffix.
_NHS_TRUST_SUFFIXES = ("NHS Trust", "NHS Foundation Trust")


def _normalise(url: str) -> str:
    """Normalise to a trailing-slash URL so dedupe and prefix checks hold."""
    return url if url.endswith("/") else url + "/"


def _path_segments(url: str) -> list[str]:
    return [part for part in urlparse(url).path.split("/") if part]


def _iter_anchors(html: str, base_url: str):
    """Yield ``(url, link_text)`` for every same-host anchor on the page.

    Hrefs are stripped of surrounding whitespace (including stray
    non-breaking spaces the live site has been observed to emit) before
    resolution. An href that is empty after stripping is skipped and
    logged rather than yielded — a single malformed anchor on an
    otherwise-good page is a data-quality blip, not the systemic layout
    drift ``run_pipeline``'s preflight probe exists to catch loudly; the
    aggregate emptiness checks in ``discover_seeds`` still raise if a
    whole page yields nothing usable. ``link_text`` is likewise stripped,
    since ``discover_trust_seeds`` matches an exact trailing suffix on it.
    """
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            logger.debug("skipping anchor with empty/whitespace-only href on %s", base_url)
            continue
        url = _normalise(urljoin(base_url, href))
        if urlparse(url).netloc == urlparse(base_url).netloc:
            yield url, anchor.get_text().strip()


def _iter_urls(html: str, base_url: str):
    """Yield absolute, same-host, normalised URLs from every anchor."""
    for url, _text in _iter_anchors(html, base_url):
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


def _is_nhs_trust_link(link_text: str) -> bool:
    """True if a candidate provider link's visible text names an NHS trust.

    Independent/private providers (Nuffield, Spire, Spamedica, Circle,
    Ramsay, CHEC, Optegra, Newmedica, ACES, Practice Plus Group, ...) use a
    "Location - Brand" link text with no such suffix, verified against the
    live site with zero exceptions.
    """
    return link_text.endswith(_NHS_TRUST_SUFFIXES)


def discover_trust_seeds(
    region_url: str, html: str, base_url: str = BASE_URL
) -> list[tuple[str, str]]:
    """Extract ``(trust_url, region)`` seeds from a region page.

    A candidate provider link is exactly one path level below the region
    URL — this excludes self links, specialty pages (two levels down) and
    links to other regions' providers. Region pages list independent/
    private providers alongside genuine NHS trusts with no DOM-level
    distinction, so candidates are additionally filtered to those whose
    visible link text ends in "NHS Trust" or "NHS Foundation Trust" —
    see ``_is_nhs_trust_link``.
    """
    region_url = _normalise(region_url)
    slug = _path_segments(region_url)[0]
    region_name = REGION_SLUG_TO_NAME.get(slug, slug)
    seeds: list[tuple[str, str]] = []
    seen: set[str] = set()
    candidate_count = 0
    for url, link_text in _iter_anchors(html, region_url):
        if not (
            url != region_url
            and url.startswith(region_url)
            and len(_path_segments(url)) == 2
            and url not in seen
        ):
            continue
        seen.add(url)
        candidate_count += 1
        if _is_nhs_trust_link(link_text):
            seeds.append((url, region_name))

    logger.info(
        "%s: %d candidate provider links, %d kept as NHS trusts",
        region_url,
        candidate_count,
        len(seeds),
    )
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
