"""Tests for defaulting, validation and filename rules."""

import datetime as dt

import pytest

from ics_maker import constants
from ics_maker.event import (
    RowError,
    build_event,
    build_events,
    parse_reminder,
    sanitize_filename,
)
from ics_maker.sheet import RawRow

TZ = "America/New_York"


def make_row(row_number=2, **values):
    return RawRow(row_number=row_number, values=values)


def test_timed_event_defaults_to_one_hour():
    spec = build_event(
        make_row(title="Meeting", start_date=dt.date(2026, 8, 31), start_time=dt.time(19, 0)),
        TZ,
    )
    assert spec.all_day is False
    assert spec.start.hour == 19
    assert spec.end - spec.start == dt.timedelta(hours=1)
    assert spec.start.tzinfo is not None


def test_default_duration_rolls_over_midnight():
    spec = build_event(
        make_row(title="Late", start_date=dt.date(2026, 8, 31), start_time=dt.time(23, 30)),
        TZ,
    )
    assert spec.end.date() == dt.date(2026, 9, 1)
    assert spec.end.hour == 0 and spec.end.minute == 30


def test_missing_start_time_implies_all_day():
    spec = build_event(make_row(title="Holiday", start_date=dt.date(2026, 8, 31)), TZ)
    assert spec.all_day is True


def test_single_day_all_day_event_ends_the_next_day():
    """RFC 5545 all-day DTEND is exclusive; Apple shows a day short without this."""
    spec = build_event(
        make_row(title="Holiday", start_date=dt.date(2026, 8, 31), all_day="yes"), TZ
    )
    assert spec.start == dt.date(2026, 8, 31)
    assert spec.end == dt.date(2026, 9, 1)


def test_multi_day_all_day_event_ends_the_day_after_the_last_day():
    spec = build_event(
        make_row(
            title="Conference",
            start_date=dt.date(2026, 8, 31),
            end_date=dt.date(2026, 9, 2),
            all_day="yes",
        ),
        TZ,
    )
    assert spec.end == dt.date(2026, 9, 3)


def test_row_timezone_overrides_the_run_default():
    spec = build_event(
        make_row(
            title="Call",
            start_date=dt.date(2026, 8, 31),
            start_time=dt.time(9, 0),
            timezone="America/Los_Angeles",
        ),
        TZ,
    )
    assert spec.tzid == "America/Los_Angeles"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("15m", dt.timedelta(minutes=15)),
        ("30 min", dt.timedelta(minutes=30)),
        ("1h", dt.timedelta(hours=1)),
        ("2 hours", dt.timedelta(hours=2)),
        ("1d", dt.timedelta(days=1)),
        ("1w", dt.timedelta(weeks=1)),
        ("45", dt.timedelta(minutes=45)),  # A bare number means minutes.
        ("15 minutes in advance", dt.timedelta(minutes=15)),  # The web form's wording.
        ("0", dt.timedelta(0)),  # Fires exactly at the start.
        ("", None),
        ("none", None),
        ("no reminder", None),
    ],
)
def test_parse_reminder(text, expected):
    assert parse_reminder(text, 2) == expected


def test_parse_reminder_rejects_gibberish():
    with pytest.raises(RowError, match="not a duration I recognize"):
        parse_reminder("soonish", 2)


def test_parse_reminder_rejects_an_unknown_unit():
    with pytest.raises(RowError, match="unknown unit"):
        parse_reminder("5 fortnights", 2)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("board-meeting", "board-meeting"),
        ("board-meeting.ics", "board-meeting"),  # A typed extension is not doubled.
        ("Q3: Review/Plan", "Q3 Review Plan"),
        ("  spaced   out  ", "spaced out"),
        ("...", ""),
        ("", ""),
        # Windows reserves these for devices, with or without an extension.
        ("CON", "CON_"),
        ("nul", "nul_"),
        ("Com1", "Com1_"),
        ("LPT9", "LPT9_"),
        # The suffix goes on the first segment: "CON.backup_" would still
        # be refused by Windows, because CON is still what precedes the dot.
        ("CON.backup", "CON_.backup"),
        ("NUL.a.b", "NUL_.a.b"),
        ("con.ics", "con_"),  # The .ics is stripped first, leaving a bare CON.
        # Names that merely start with a reserved word are fine as they are.
        ("CONCERT", "CONCERT"),
        ("CON-call", "CON-call"),
        ("COM10", "COM10"),
        ("AUXILIARY", "AUXILIARY"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_a_reserved_name_stays_within_the_length_limit():
    """The suffix must never push a name past what the limit allows."""
    for reserved in constants.WINDOWS_RESERVED_NAMES:
        assert len(sanitize_filename(reserved)) <= constants.MAX_FILENAME_LENGTH


def test_no_reserved_name_survives_sanitizing():
    """Whatever comes out, Windows must be willing to create it.

    Checked against the segment before the first dot, since that is the
    part Windows actually judges -- with any extension appended.
    """
    for reserved in constants.WINDOWS_RESERVED_NAMES:
        for raw in (reserved, reserved.lower(), f"{reserved}.backup", f"{reserved}.a.b"):
            cleaned = sanitize_filename(raw)
            head = f"{cleaned}.ics".split(".")[0]
            assert head.upper() not in constants.WINDOWS_RESERVED_NAMES, raw


def test_a_reserved_filename_reaches_the_written_file(tmp_path):
    """The fix has to survive the whole path, not just the helper."""
    spec = build_event(
        make_row(title="Standup", start_date=dt.date(2026, 8, 31), filename="PRN"), TZ
    )

    assert spec.filename == "PRN_"


def test_blank_filename_falls_back_to_the_row_number():
    spec = build_event(make_row(row_number=7, title="Holiday", start_date=dt.date(2026, 8, 31)), TZ)
    assert spec.filename == "ics-7"


def test_unusable_filename_also_falls_back_to_the_row_number():
    spec = build_event(
        make_row(row_number=4, title="Holiday", start_date=dt.date(2026, 8, 31), filename="///"),
        TZ,
    )
    assert spec.filename == "ics-4"


def test_missing_title_is_a_row_error():
    with pytest.raises(RowError, match="'Title' is empty"):
        build_event(make_row(start_date=dt.date(2026, 8, 31)), TZ)


def test_missing_start_date_is_a_row_error():
    with pytest.raises(RowError, match="'Start Date' is empty"):
        build_event(make_row(title="Meeting"), TZ)


def test_end_before_start_is_a_row_error():
    with pytest.raises(RowError, match="ends .* before it starts"):
        build_event(
            make_row(
                title="Backwards",
                start_date=dt.date(2026, 8, 31),
                start_time=dt.time(19, 0),
                end_time=dt.time(18, 0),
            ),
            TZ,
        )


def test_unknown_timezone_is_a_row_error():
    with pytest.raises(RowError, match="not a known timezone"):
        build_event(
            make_row(title="Meeting", start_date=dt.date(2026, 8, 31), timezone="Mars/Olympus"),
            TZ,
        )


def test_build_events_collects_errors_instead_of_stopping():
    rows = [
        make_row(row_number=2, title="Good", start_date=dt.date(2026, 8, 31)),
        make_row(row_number=3, start_date=dt.date(2026, 8, 31)),  # No title.
        make_row(row_number=4, title="Also good", start_date=dt.date(2026, 9, 1)),
    ]
    events, errors = build_events(rows, TZ)
    assert [event.row_number for event in events] == [2, 4]
    assert [error.row_number for error in errors] == [3]


def test_duplicate_filenames_are_rejected_rather_than_overwriting():
    rows = [
        make_row(row_number=2, title="A", start_date=dt.date(2026, 8, 31), filename="same"),
        make_row(row_number=3, title="B", start_date=dt.date(2026, 9, 1), filename="SAME"),
    ]
    events, errors = build_events(rows, TZ)
    assert len(events) == 1
    assert "already used by row 2" in errors[0].message
