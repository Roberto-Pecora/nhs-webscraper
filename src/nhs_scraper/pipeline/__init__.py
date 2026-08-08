"""Pipeline stages: discovery, extraction, normalisation, orchestration."""

from nhs_scraper.pipeline.extract import extract_waiting_times

__all__ = ["extract_waiting_times"]
