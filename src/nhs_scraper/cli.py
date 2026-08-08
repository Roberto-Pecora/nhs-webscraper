"""Command-line entry point: ``nhs-scraper``.

The backend is constructed lazily inside ``build_backend`` so importing
the CLI never pulls optional crawl dependencies into the default install.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from nhs_scraper.io.csv_handler import write_records_csv
from nhs_scraper.pipeline.run import run_pipeline
from nhs_scraper.ports import CrawlBackend, CrawlOptions

DEFAULT_SEEDS: list[tuple[str, str]] = [
    ("https://www.myplannedcare.nhs.uk/seast/royal-berkshire/", "South East"),
]


def parse_seed(value: str) -> tuple[str, str]:
    """Parse a ``URL=REGION`` seed argument."""
    url, sep, region = value.rpartition("=")
    if not sep or not url.strip() or not region.strip():
        raise argparse.ArgumentTypeError(
            f"seeds must be URL=REGION, e.g. https://…/trust/=South East; got {value!r}"
        )
    return url.strip(), region.strip()


def build_backend(name: str) -> CrawlBackend:
    """Construct a backend by name; imports are lazy on purpose."""
    if name == "crawl4ai":
        from nhs_scraper.backends.crawl4ai_backend import Crawl4AIBackend

        return Crawl4AIBackend()
    raise ValueError(f"unknown backend {name!r}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nhs-scraper",
        description="Extract NHS My Planned Care waiting times to CSV.",
    )
    parser.add_argument("--backend", default="crawl4ai", help="crawl backend to use")
    parser.add_argument(
        "--seed",
        action="append",
        type=parse_seed,
        default=None,
        metavar="URL=REGION",
        help="trust/region seed (repeatable); defaults to a built-in example",
    )
    parser.add_argument("--output", default="output/my_planned_care.csv")
    parser.add_argument("--limit", type=int, default=100, help="max pages per crawl")
    parser.add_argument("--max-depth", type=int, default=2, help="max crawl depth")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    backend = build_backend(args.backend)
    seeds = args.seed or DEFAULT_SEEDS
    options = CrawlOptions(limit=args.limit, max_depth=args.max_depth)

    result = asyncio.run(run_pipeline(backend, seeds, options))
    path = write_records_csv(result.records, args.output)
    print(f"run {result.run.run_id}: wrote {len(result.records)} records to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
