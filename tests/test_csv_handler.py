"""Unit tests for CSV persistence: column contract and edge cases."""

from __future__ import annotations

import csv

import pytest

from nhs_scraper.domain import WaitingTimeRecord
from nhs_scraper.io.csv_handler import (
    COLUMNS,
    read_records_csv,
    write_records_csv,
)


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

    def test_integer_columns_never_serialise_as_floats(self, tmp_path, load_golden):
        # Regression: a column mixing ints and None becomes float64 in
        # pandas and serialises as 8.0 without the Int64 cast.
        records = make_records(load_golden)
        records[0] = WaitingTimeRecord.from_dict(
            {**records[0].to_dict(), "average_wait_weeks": None}
        )
        path = write_records_csv(records, tmp_path / "out.csv")

        text = path.read_text(encoding="utf-8")

        assert ".0" not in text
        assert ",5," in text  # the remaining int stays a plain integer

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


class TestReadRecordsCsv:
    def test_round_trip(self, tmp_path, load_golden):
        records = make_records(load_golden)
        path = write_records_csv(records, tmp_path / "out.csv")

        assert read_records_csv(path) == records

    def test_none_round_trip(self, tmp_path, load_golden):
        record = WaitingTimeRecord.from_dict(
            {
                **make_records(load_golden)[0].to_dict(),
                "average_wait_weeks": None,
                "page_last_updated": None,
            }
        )
        path = write_records_csv([record], tmp_path / "out.csv")

        (read_back,) = read_records_csv(path)
        assert read_back.average_wait_weeks is None
        assert read_back.page_last_updated is None

    def test_tolerates_legacy_float_formatting(self, tmp_path):
        path = tmp_path / "legacy.csv"
        path.write_text(
            ",".join(COLUMNS)
            + "\nSouth East,RBH,ENT,https://www.myplannedcare.nhs.uk/x/,treatment,8.0,16.0,2026-01-26\n",
            encoding="utf-8",
        )

        (record,) = read_records_csv(path)
        assert record.average_wait_weeks == 8
        assert record.patients_seen_within_weeks == 16

    def test_rejects_unexpected_header(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("wrong,header\n1,2\n", encoding="utf-8")

        with pytest.raises(ValueError, match="unexpected CSV header"):
            read_records_csv(path)

    def test_rejects_non_integral_weeks(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text(
            ",".join(COLUMNS)
            + "\nSouth East,RBH,ENT,https://www.myplannedcare.nhs.uk/x/,treatment,8.5,16,2026-01-26\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="whole number of weeks"):
            read_records_csv(path)
