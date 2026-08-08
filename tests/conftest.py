"""Shared pytest helpers for the offline test-suite.

Fixtures on disk are the characterisation baseline: they were captured from
live My Planned Care pages and must not be edited to make new code pass.
Add a *new* fixture when the site layout changes, and record the date.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def golden_dir() -> Path:
    return GOLDEN_DIR


@pytest.fixture()
def load_fixture():
    def _load(name: str) -> str:
        return (FIXTURES_DIR / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture()
def load_golden():
    def _load(name: str) -> list[dict]:
        return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))

    return _load
