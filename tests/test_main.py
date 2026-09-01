"""End-to-end tests for the CLI, from template through to written files.

These must never touch Qt: the file picker is only reached when no
spreadsheet argument is given, and every test here passes one.
"""

import datetime as dt
import sys

import pytest
from openpyxl import Workbook

from ics_maker import constants
from ics_maker.main import build_parser, main, resolve_template_path, run
from ics_maker.template import write_template


def invoke(*argv):
    """Run the CLI with the given arguments and return its exit code."""
    return run(build_parser().parse_args([str(a) for a in argv]))


def write_sheet(path, rows, header=("Title", "Start Date", "Start Time", "Filename")):
    workbook = Workbook()
    workbook.active.append(list(header))
    for row in rows:
        workbook.active.append(list(row))
    workbook.save(path)
    return path


def test_template_round_trips_through_the_generator(tmp_path):
    sheet = write_template(tmp_path / "starter.xlsx")
    output = tmp_path / "out"

    assert invoke(sheet, "-o", output) == 0

    written = sorted(p.name for p in output.glob("*.ics"))
    assert written == ["board-meeting.ics", "conference.ics", "ics-3.ics", "ics-5.ics"]


def test_blank_filename_row_is_named_for_its_sheet_row(tmp_path):
    sheet = write_sheet(
        tmp_path / "e.xlsx",
        [
            ["First", dt.date(2026, 8, 31), dt.time(9, 0), "named"],
            ["Second", dt.date(2026, 9, 1), dt.time(9, 0), None],
        ],
    )
    output = tmp_path / "out"
    assert invoke(sheet, "-o", output) == 0
    assert (output / "named.ics").exists()
    assert (output / "ics-3.ics").exists()  # Second event is on sheet row 3.


def test_bad_rows_are_skipped_but_good_ones_are_written(tmp_path):
    sheet = write_sheet(
        tmp_path / "e.xlsx",
        [
            ["Good", dt.date(2026, 8, 31), dt.time(9, 0), None],
            [None, dt.date(2026, 8, 31), None, None],  # No title.
        ],
    )
    output = tmp_path / "out"
    assert invoke(sheet, "-o", output) == 1  # Non-zero because a row failed.
    assert len(list(output.glob("*.ics"))) == 1


def test_strict_writes_nothing_when_any_row_fails(tmp_path):
    sheet = write_sheet(
        tmp_path / "e.xlsx",
        [
            ["Good", dt.date(2026, 8, 31), dt.time(9, 0), None],
            [None, dt.date(2026, 8, 31), None, None],
        ],
    )
    output = tmp_path / "out"
    assert invoke(sheet, "-o", output, "--strict") == 1
    assert not output.exists()


def test_dry_run_writes_nothing(tmp_path):
    sheet = write_sheet(tmp_path / "e.xlsx", [["Good", dt.date(2026, 8, 31), dt.time(9, 0), None]])
    output = tmp_path / "out"
    assert invoke(sheet, "-o", output, "--dry-run") == 0
    assert not output.exists()


def test_rerunning_overwrites_instead_of_accumulating(tmp_path):
    sheet = write_sheet(tmp_path / "e.xlsx", [["Good", dt.date(2026, 8, 31), dt.time(9, 0), None]])
    output = tmp_path / "out"
    invoke(sheet, "-o", output)
    invoke(sheet, "-o", output)
    assert len(list(output.glob("*.ics"))) == 1


def test_missing_file_and_bad_timezone_exit_with_two(tmp_path):
    sheet = write_sheet(tmp_path / "e.xlsx", [["Good", dt.date(2026, 8, 31), dt.time(9, 0), None]])
    assert invoke(tmp_path / "nope.xlsx", "-o", tmp_path / "out") == 2
    assert invoke(sheet, "-o", tmp_path / "out", "--timezone", "Mars/Olympus") == 2


def test_header_only_sheet_is_not_an_error(tmp_path):
    sheet = write_sheet(tmp_path / "e.xlsx", [])
    assert invoke(sheet, "-o", tmp_path / "out") == 0


@pytest.mark.parametrize(
    "raw, expected_name",
    [
        ("", constants.TEMPLATE_FILENAME),
        ("mysheet.xlsx", "mysheet.xlsx"),
        ("mysheet", "mysheet.xlsx"),  # A missing extension is supplied.
    ],
)
def test_resolve_template_path(raw, expected_name):
    assert resolve_template_path(raw).name == expected_name


def test_template_flag_writes_a_workbook_and_exits_zero(tmp_path, monkeypatch, capsys):
    target = tmp_path / "fresh.xlsx"
    monkeypatch.setattr(sys, "argv", ["ics-maker", "--template", str(target)])
    assert main() == 0
    assert target.is_file()
    assert "Wrote template" in capsys.readouterr().out


def test_the_cli_never_loads_qt(tmp_path, monkeypatch):
    """The picker import is local so plain runs stay headless."""
    sheet = write_sheet(tmp_path / "e.xlsx", [["Good", dt.date(2026, 8, 31), dt.time(9, 0), None]])
    monkeypatch.setattr(sys, "argv", ["ics-maker", str(sheet), "-o", str(tmp_path / "out")])
    main()
    assert not [name for name in sys.modules if name.startswith("PySide6")]
