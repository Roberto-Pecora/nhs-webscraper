# nhs-webscraper

A modular, unit-test-driven pipeline for extracting specialty waiting-time
data from the [NHS My Planned Care](https://www.myplannedcare.nhs.uk/)
platform.

This repository is a ground-up rebuild of the original Selenium-coupled
[`nhs_webscraper`](https://github.com/Hydaspex/nhs_webscraper). The crawl
backend is pluggable (legacy Selenium compatibility adapter, Firecrawl API),
whilst parsing, normalisation and persistence are pure, offline-testable
units.

## Design principles

1. **Tests lead.** Behaviour is pinned by characterisation tests before any
   production code is written or moved.
2. **Pure core.** Extraction and normalisation operate on immutable domain
   objects — never on a live WebDriver or HTTP response.
3. **Ports and adapters.** Backends implement a single `CrawlBackend`
   interface; the pipeline does not know which backend is active.
4. **Offline by default.** Unit and contract tests require no browser, no
   network and no API keys. Live integration tests are opt-in.

## Layout

```text
src/nhs_scraper/
  domain/         # immutable models: Page, WaitingTimeRecord, CrawlRun
  ports.py        # CrawlBackend interface
  backends/       # firecrawl.py, legacy_selenium.py
  pipeline/       # discover, extract, normalise, run
  io/             # csv_handler, fixtures
tests/
  fixtures/       # captured HTML pages (characterisation baseline)
  golden/         # expected extraction output per fixture
```

## Roadmap (one PR per step)

1. Characterisation baseline — fixtures, golden dataset, schema tests
2. Domain models with validation tests
3. `CrawlBackend` port + pure extraction against fixtures
4. Firecrawl backend with mocked unit tests and contract tests
5. Pipeline orchestration + CSV output with fake-backend integration tests
6. Legacy-vs-modern parity diff tooling; removal of Selenium

## Development

```bash
pip install -e .[dev]
pytest
ruff check .
```
