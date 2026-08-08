"""Unit tests for CSV persistence: column contract and edge cases."""

from __future__ import annotations

import csv

from nhs_scraper.domain import WaitingTimeRecord
from nhs_scraper.io.csv_handler import COLUMNS, write_records_csv


def make_records(load_golden):
    return [
        WaitingTimeRecord.from_dict(data)
        for data in load_golden("royal_berkshire_expected.json")
    ]


class TestWriteRecordsCsv:
    def test_header_and_row_contract(self, tmp_path, load_golden):
        path = write_records_csv(make_records(load_golden), tmp_path / "out.csv")

        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))

        assert rows[0] == COLUMNS
        assert len(rows) == 5
        assert rows[1][4] == "first_outpatient_appointment"
        assert rows[1][5] == "2"

    def test_none_written_as_empty_cell(self, tmp_path, load_golden):
        records = make_records(load_golden)
        record = WaitingTimeRecord.from_dict(
            {**records[0].to_dict(), "average_wait_weeks": None}
        )
        path = write_records_csv([record], tmp_path / "out.csv")

        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))

        assert rows[1][5] == ""

    def test_empty_input_writes_header_only(self, tmp_path):
        path = write_records_csv([], tmp_path / "out.csv")

        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))

        assert rows == [COLUMNS]

    def test_parent_directories_created(self, tmp_path, load_golden):
        path = write_records_csv(
            make_records(load_golden), tmp_path / "nested" / "deep" / "out.csv"
        )
        assert path.exists()
