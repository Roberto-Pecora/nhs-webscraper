"""Unit tests for the row-level parity diff and the diff CLI."""

from __future__ import annotations

from datetime import date

from nhs_scraper.cli import diff_main, parse_diff_args
from nhs_scraper.domain import Metric, WaitingTimeRecord
from nhs_scraper.io.csv_handler import write_records_csv
from nhs_scraper.pipeline.diff import diff_records, format_change


def rec(specialty, average=8, within=16, updated=date(2026, 1, 26), provider="RBH"):
    return WaitingTimeRecord(
        region="South East",
        provider=provider,
        specialty=specialty,
        source_url="https://www.myplannedcare.nhs.uk/x/",
        metric=Metric.TREATMENT,
        average_wait_weeks=average,
        patients_seen_within_weeks=within,
        page_last_updated=updated,
    )


class TestDiffRecords:
    def test_identical_inputs(self):
        records = [rec("Cardiology"), rec("ENT")]
        report = diff_records(records, records)

        assert report.is_identical
        assert report.total_changes == 0
        assert report.unchanged_count == 2

    def test_added_only(self):
        report = diff_records([rec("ENT")], [rec("ENT"), rec("Urology")])

        assert [c.key[2] for c in report.added] == ["Urology"]
        assert report.added[0].old is None
        assert not report.removed and not report.changed

    def test_removed_only(self):
        report = diff_records([rec("ENT"), rec("Urology")], [rec("ENT")])

        assert [c.key[2] for c in report.removed] == ["Urology"]
        assert report.removed[0].new is None

    def test_changed_with_field_level_detail(self):
        old = rec("Cardiology", average=8, within=16, updated=date(2026, 1, 26))
        new = rec("Cardiology", average=10, within=16, updated=date(2026, 1, 26))

        report = diff_records([old], [new])

        (change,) = report.changed
        assert change.changed_fields == ("average_wait_weeks",)
        assert change.old.average_wait_weeks == 8
        assert change.new.average_wait_weeks == 10
        assert report.unchanged_count == 0

    def test_none_to_value_transition_counts_as_changed(self):
        old = rec("ENT", average=None)
        new = rec("ENT", average=4)

        report = diff_records([old], [new])

        assert report.changed[0].changed_fields == ("average_wait_weeks",)

    def test_mixed_scenario_summary(self):
        old = [rec("Breast Surgery"), rec("Cardiology"), rec("ENT")]
        new = [rec("Cardiology", average=10), rec("ENT"), rec("Urology")]

        report = diff_records(old, new)

        assert len(report.added) == 1
        assert len(report.removed) == 1
        assert len(report.changed) == 1
        assert report.unchanged_count == 1
        assert report.summary() == (
            "3 change(s): +1 added, -1 removed, ~1 changed, =1 unchanged"
        )


class TestFormatChange:
    def test_added_line(self):
        change = diff_records([], [rec("Urology")]).added[0]
        assert format_change(change) == "+ South East / RBH / Urology / treatment"

    def test_changed_line_shows_old_and_new_values(self):
        change = diff_records([rec("ENT", average=4)], [rec("ENT", average=6)]).changed[0]
        line = format_change(change)

        assert line.startswith("~ South East / RBH / ENT / treatment")
        assert "average_wait_weeks: 4 -> 6" in line


class TestDiffCli:
    def _write_pair(self, tmp_path, old_records, new_records):
        old_path = write_records_csv(old_records, tmp_path / "old.csv")
        new_path = write_records_csv(new_records, tmp_path / "new.csv")
        return old_path, new_path

    def test_parse_diff_args(self):
        args = parse_diff_args(["old.csv", "new.csv"])
        assert args.old == "old.csv" and args.new == "new.csv"

    def test_exit_zero_when_identical(self, tmp_path, capsys):
        old_path, new_path = self._write_pair(tmp_path, [rec("ENT")], [rec("ENT")])

        assert diff_main([str(old_path), str(new_path)]) == 0
        assert "0 change(s)" in capsys.readouterr().out

    def test_exit_one_and_report_when_changed(self, tmp_path, capsys):
        old_path, new_path = self._write_pair(
            tmp_path, [rec("ENT", average=4)], [rec("ENT", average=6), rec("Urology")]
        )

        assert diff_main([str(old_path), str(new_path)]) == 1
        out = capsys.readouterr().out
        assert "2 change(s)" in out
        assert "+ South East / RBH / Urology / treatment" in out
        assert "average_wait_weeks: 4 -> 6" in out
