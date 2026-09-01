"""Tests for header matching and cell coercion."""

import datetime as dt

import pytest
from openpyxl import Workbook

from ics_maker.sheet import (
    SheetError,
    coerce_bool,
    coerce_date,
    coerce_time,
    normalize_header,
    read_rows,
)


@pytest.mark.parametrize(
    "text", ["Start Date", "start_date", "START-DATE", " startdate ", "Start.Date"]
)
def test_header_variants_collapse_to_one_key(text):
    assert normalize_header(text) == "startdate"


@pytest.mark.parametrize(
    "value, expected",
    [
        (dt.datetime(2026, 8, 31, 19, 0), dt.date(2026, 8, 31)),
        (dt.date(2026, 8, 31), dt.date(2026, 8, 31)),
        ("08/31/2026", dt.date(2026, 8, 31)),
        ("2026-08-31", dt.date(2026, 8, 31)),
        ("31.08.2026", dt.date(2026, 8, 31)),
        (None, None),
        ("   ", None),
    ],
)
def test_coerce_date(value, expected):
    assert coerce_date(value, "Start Date") == expected


def test_coerce_date_rejects_gibberish():
    with pytest.raises(ValueError, match="not a date I recognize"):
        coerce_date("next tuesday", "Start Date")


@pytest.mark.parametrize(
    "value, expected",
    [
        (dt.time(19, 0), dt.time(19, 0)),
        (dt.datetime(2026, 8, 31, 19, 30), dt.time(19, 30)),
        ("19:00", dt.time(19, 0)),
        ("7:00 PM", dt.time(19, 0)),
        ("7PM", dt.time(19, 0)),
        (0.5, dt.time(12, 0)),  # Excel stores a bare time as a fraction of a day.
        (dt.timedelta(hours=9, minutes=15), dt.time(9, 15)),
        (None, None),
    ],
)
def test_coerce_time(value, expected):
    assert coerce_time(value, "Start Time") == expected


def test_coerce_time_rejects_gibberish():
    with pytest.raises(ValueError, match="not a time I recognize"):
        coerce_time("morning", "Start Time")


@pytest.mark.parametrize("value", ["yes", "Y", "TRUE", "x", 1, True, "all day"])
def test_coerce_bool_true(value):
    assert coerce_bool(value, "All Day") is True


@pytest.mark.parametrize("value", [None, "", "no", "FALSE", 0, False])
def test_coerce_bool_false(value):
    assert coerce_bool(value, "All Day") is False


def _workbook(tmp_path, rows, name="events.xlsx"):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    path = tmp_path / name
    workbook.save(path)
    return path


def test_read_rows_maps_headers_and_numbers_rows(tmp_path):
    path = _workbook(
        tmp_path,
        [
            ["title", "START DATE", "Ignored Column", "Start_Time"],
            ["Meeting", dt.date(2026, 8, 31), "junk", dt.time(19, 0)],
        ],
    )
    rows = read_rows(path)
    assert len(rows) == 1
    # Row 1 is the header, so the first data row is row 2.
    assert rows[0].row_number == 2
    assert rows[0].text("title") == "Meeting"
    assert rows[0].raw("start_date") == dt.datetime(2026, 8, 31)


def test_read_rows_skips_blank_spacer_rows(tmp_path):
    path = _workbook(
        tmp_path,
        [
            ["Title", "Start Date"],
            ["First", dt.date(2026, 8, 31)],
            [None, None],
            ["Second", dt.date(2026, 9, 1)],
        ],
    )
    rows = read_rows(path)
    assert [row.row_number for row in rows] == [2, 4]


def test_read_rows_requires_the_mandatory_columns(tmp_path):
    path = _workbook(tmp_path, [["Location", "Description"], ["here", "there"]])
    with pytest.raises(SheetError, match="missing required column"):
        read_rows(path)


def test_read_rows_reports_an_unknown_sheet_name(tmp_path):
    path = _workbook(tmp_path, [["Title", "Start Date"]])
    with pytest.raises(SheetError, match="No sheet named"):
        read_rows(path, sheet_name="Nope")
