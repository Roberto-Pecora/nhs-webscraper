"""Pipeline stages: preflight, extraction, normalisation, orchestration, diff."""

from nhs_scraper.pipeline.diff import ParityReport, RecordChange, diff_records, format_change
from nhs_scraper.pipeline.extract import extract_waiting_times
from nhs_scraper.pipeline.normalise import normalise_records
from nhs_scraper.pipeline.preflight import LayoutDriftError, LayoutProbeResult, probe_layout
from nhs_scraper.pipeline.run import PipelineResult, run_pipeline

__all__ = [
    "LayoutDriftError",
    "LayoutProbeResult",
    "ParityReport",
    "PipelineResult",
    "RecordChange",
    "diff_records",
    "extract_waiting_times",
    "format_change",
    "normalise_records",
    "probe_layout",
    "run_pipeline",
]
