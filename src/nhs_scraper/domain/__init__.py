"""Domain models: the pure, validated core of the pipeline."""

from nhs_scraper.domain.models import CrawlRun, Metric, Page, WaitingTimeRecord

__all__ = ["CrawlRun", "Metric", "Page", "WaitingTimeRecord"]
