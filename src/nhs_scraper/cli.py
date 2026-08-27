"""Command-line entry points: ``nhs-scraper`` and ``nhs-scraper-diff``.

The crawl backend is constructed lazily inside ``build_backend`` so
importing the CLI never pulls optional crawl dependencies into the
default install.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence

from nhs_scraper.io.csv_handler import read_records_csv, write_records_csv
from nhs_scraper.pipeline.diff import diff_records, format_change
from nhs_scraper.pipeline.discover import discover_seeds
from nhs_scraper.pipeline.preflight import LayoutDriftError
from nhs_scraper.pipeline.run import run_pipeline
from nhs_scraper.ports import CrawlBackend, CrawlOptions, RetryPolicy

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


def build_backend(name: str, retry_policy: RetryPolicy | None = None) -> CrawlBackend:
    """Construct a backend by name; imports are lazy on purpose."""
    if name == "crawl4ai":
        from nhs_scraper.backends.crawl4ai_backend import Crawl4AIBackend

        return Crawl4AIBackend(retry_policy=retry_policy)
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
    parser.add_argument(
        "--discover",
        action="store_true",
        help="enumerate every region/trust seed from the live site "
        "(full-site run; mutually exclusive with --seed)",
    )
    parser.add_argument("--output", default="output/my_planned_care.csv")
    parser.add_argument("--limit", type=int, default=100, help="max pages per crawl")
    parser.add_argument("--max-depth", type=int, default=2, help="max crawl depth")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="max seeds crawled concurrently (default: 8)",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="max attempts per request for transient failures",
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=2.0,
        help="linear backoff base in seconds between retry attempts",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="skip the pre-flight layout probe (not recommended for scheduled runs)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    # Without this, INFO-level logs from discover.py/run.py (e.g. the
    # per-region "kept as NHS trusts" line) never reach stdout in a real
    # run — the loggers exist but nothing has configured a handler/level.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args(argv)
    if args.discover and args.seed:
        print("--discover and --seed are mutually exclusive")
        return 1

    retry_policy = RetryPolicy(attempts=args.attempts, backoff_seconds=args.backoff)
    backend = build_backend(args.backend, retry_policy=retry_policy)

    if args.discover:
        try:
            seeds = asyncio.run(discover_seeds(backend))
        except Exception as exc:
            # Never fall back to DEFAULT_SEEDS here: a failed discovery
            # must not silently degrade a full-site run into a one-trust run.
            print(f"seed discovery failed: {exc}")
            return 1
        print(f"discovered {len(seeds)} trust seeds across the site")
    else:
        seeds = args.seed or DEFAULT_SEEDS

    options = CrawlOptions(limit=args.limit, max_depth=args.max_depth, concurrency=args.concurrency)
    try:
        result = asyncio.run(
            run_pipeline(backend, seeds, options, preflight=not args.no_preflight)
        )
    except LayoutDriftError as exc:
        # Distinct exit code so scheduled workflows can alert on drift
        # specifically rather than treating it as a generic failure.
        print("layout drift detected — aborting before crawl:")
        for failure in exc.failures:
            print(f"  - {failure}")
        return 2

    path = write_records_csv(result.records, args.output)
    print(f"run {result.run.run_id}: wrote {len(result.records)} records to {path}")
    if result.failed_pages:
        print(f"warning: {len(result.failed_pages)} page(s) failed after retries:")
        for url in result.failed_pages:
            print(f"  - {url}")
    return 0


def parse_diff_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nhs-scraper-diff",
        description="Row-level diff between two record CSVs (old vs new).",
    )
    parser.add_argument("old", help="baseline CSV (e.g. last week's output)")
    parser.add_argument("new", help="candidate CSV (e.g. this week's output)")
    return parser.parse_args(argv)


def diff_main(argv: Sequence[str] | None = None) -> int:
    """Diff two CSVs; exit 0 when identical, 1 when changes are found.

    The exit code makes the diff usable as a CI gate: a scheduled run can
    compare this week's output against last week's and fail loudly when
    waiting times move.
    """
    args = parse_diff_args(argv)
    report = diff_records(read_records_csv(args.old), read_records_csv(args.new))

    print(report.summary())
    for change in (*report.added, *report.removed, *report.changed):
        print(format_change(change))
    return 0 if report.is_identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
