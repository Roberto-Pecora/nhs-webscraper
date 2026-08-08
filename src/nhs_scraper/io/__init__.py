"""Persistence adapters for pipeline output."""

from nhs_scraper.io.csv_handler import COLUMNS, read_records_csv, write_records_csv

__all__ = ["COLUMNS", "read_records_csv", "write_records_csv"]
