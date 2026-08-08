"""Pipeline stages: discovery, extraction, normalisation, orchestration."""

from nhs_scraper.pipeline.extract import extract_waiting_times
from nhs_scraper.pipeline.normalise import normalise_records
from nhs_scraper.pipeline.run import PipelineResult, run_pipeline

__all__ = [
    "PipelineResult",
    "extract_waiting_times",
    "normalise_records",
    "run_pipeline",
]
