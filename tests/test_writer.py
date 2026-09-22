"""Tests for the generated .ics text, including a round-trip parse."""

import datetime as dt

import pytest
from icalendar import Calendar

from ics_maker import constants
from ics_maker.event import build_event
from ics_maker.sheet import RawRow
from ics_maker.writer import build_calendar, make_uid, unique_filename, write_event

TZ = "America/New_York"


def make_spec(row_number=2, **values):
    return build_event(RawRow(row_number=row_number, values=values), TZ)


def ical_text(spec):
    return build_calendar(spec).to_ical().decode()


@pytest.fixture
def timed_spec():
    return make_spec(
        title="Board Meeting",
        location="Conference Room B",
        start_date=dt.date(2026, 8, 31),
        start_time=dt.time(19, 0),
        end_time=dt.time(20, 30),
        description="Quarterly review.\nBring the agenda.",
        reminder="15m",
        url="https://example.com/agenda",
        filename="board-meeting",
    )


@pytest.fixture
def all_day_spec():
    return make_spec(title="Company Holiday", start_date=dt.date(2026, 8, 31), all_day="yes")


def test_timed_event_carries_a_tzid_and_a_matching_vtimezone(timed_spec):
    text = ical_text(timed_spec)
    assert "BEGIN:VTIMEZONE" in text
    assert "TZID:America/New_York" in text
    assert "DTSTART;TZID=America/New_York:20260831T190000" in text
    assert "DTEND;TZID=America/New_York:20260831T203000" in text


def test_all_day_event_uses_dates_and_no_vtimezone(all_day_spec):
    text = ical_text(all_day_spec)
    assert "BEGIN:VTIMEZONE" not in text
    assert "DTSTART;VALUE=DATE:20260831" in text
    # Exclusive end: the day after the single day the event covers.
    assert "DTEND;VALUE=DATE:20260901" in text


def test_reminder_becomes_a_negative_trigger_alarm(timed_spec):
    text = ical_text(timed_spec)
    assert "BEGIN:VALARM" in text
    assert "ACTION:DISPLAY" in text
    # icalendar omits the optional VALUE=DURATION param; DURATION is the
    # default value type for TRIGGER, so a bare negative duration is correct.
    assert "TRIGGER:-PT15M" in text


def test_no_reminder_means_no_alarm(all_day_spec):
    assert "BEGIN:VALARM" not in ical_text(all_day_spec)


def test_zero_reminder_fires_at_the_start():
    spec = make_spec(
        title="Now", start_date=dt.date(2026, 8, 31), start_time=dt.time(19, 0), reminder="0"
    )
    assert "TRIGGER:P0D" in ical_text(spec)


def test_description_newlines_and_commas_are_escaped():
    spec = make_spec(
        title="Meeting",
        start_date=dt.date(2026, 8, 31),
        description="First line, with a comma.\nSecond line; with a semicolon.",
    )
    text = ical_text(spec)
    assert (
        "DESCRIPTION:First line\\, with a comma.\\nSecond line\\; with a semicolon."
        in text
    )


def test_uid_is_stable_across_runs(timed_spec):
    assert make_uid(timed_spec) == make_uid(timed_spec)
    other = make_spec(title="Different", start_date=dt.date(2026, 8, 31), filename="other")
    assert make_uid(timed_spec) != make_uid(other)


def test_written_file_uses_crlf_line_endings(tmp_path, timed_spec):
    path = write_event(timed_spec, tmp_path)
    raw = path.read_bytes()
    assert path.name == "board-meeting.ics"
    assert b"\r\n" in raw
    # No bare LF anywhere: every newline must be part of a CRLF pair.
    assert raw.replace(b"\r\n", b"") .count(b"\n") == 0


def test_rerunning_overwrites_rather_than_duplicating(tmp_path, timed_spec):
    write_event(timed_spec, tmp_path)
    write_event(timed_spec, tmp_path)
    assert len(list(tmp_path.glob("*.ics"))) == 1


def test_round_trip_parse_recovers_the_spreadsheet_values(tmp_path, timed_spec):
    path = write_event(timed_spec, tmp_path)
    calendar = Calendar.from_ical(path.read_bytes())
    event = next(c for c in calendar.walk("VEVENT"))

    assert str(event["SUMMARY"]) == "Board Meeting"
    assert str(event["LOCATION"]) == "Conference Room B"
    assert str(event["URL"]) == "https://example.com/agenda"
    assert "Bring the agenda." in str(event["DESCRIPTION"])

    start = event["DTSTART"].dt
    end = event["DTEND"].dt
    assert (start.year, start.month, start.day, start.hour) == (2026, 8, 31, 19)
    assert end - start == dt.timedelta(minutes=90)
    # The offset must be EDT (-4), not the year-round EST the VTIMEZONE
    # would report if the daylight rules were dropped.
    assert start.utcoffset() == dt.timedelta(hours=-4)


def test_round_trip_parse_of_an_all_day_event(tmp_path, all_day_spec):
    path = write_event(all_day_spec, tmp_path)
    event = next(c for c in Calendar.from_ical(path.read_bytes()).walk("VEVENT"))
    assert event["DTSTART"].dt == dt.date(2026, 8, 31)
    assert event["DTEND"].dt == dt.date(2026, 9, 1)


def test_winter_event_resolves_to_standard_time(tmp_path):
    spec = make_spec(title="Winter", start_date=dt.date(2026, 1, 15), start_time=dt.time(9, 0))
    path = write_event(spec, tmp_path)
    event = next(c for c in Calendar.from_ical(path.read_bytes()).walk("VEVENT"))
    assert event["DTSTART"].dt.utcoffset() == dt.timedelta(hours=-5)


# --- unique_filename: the --form path's collision handling -------------------


def test_an_unused_name_is_left_alone(tmp_path):
    assert unique_filename("book-club", tmp_path) == "book-club"


def test_a_missing_output_dir_means_nothing_is_taken(tmp_path):
    assert unique_filename("book-club", tmp_path / "not-created-yet") == "book-club"


def test_a_taken_name_gets_numbered(tmp_path):
    (tmp_path / "book-club.ics").touch()
    assert unique_filename("book-club", tmp_path) == "book-club-1"


def test_numbering_keeps_counting_past_the_ones_already_there(tmp_path):
    for name in ("book-club.ics", "book-club-1.ics", "book-club-2.ics"):
        (tmp_path / name).touch()
    assert unique_filename("book-club", tmp_path) == "book-club-3"


def test_only_the_ics_extension_counts_as_taken(tmp_path):
    """A same-named .txt is not something we would overwrite."""
    (tmp_path / "book-club.txt").touch()
    assert unique_filename("book-club", tmp_path) == "book-club"


def test_numbering_stays_within_the_filename_length_limit(tmp_path):
    long_stem = "x" * constants.MAX_FILENAME_LENGTH
    (tmp_path / f"{long_stem}.ics").touch()

    numbered = unique_filename(long_stem, tmp_path)

    assert numbered.endswith("-1")
    assert len(numbered) <= constants.MAX_FILENAME_LENGTH


def test_a_numbered_event_gets_its_own_uid(timed_spec, tmp_path):
    """A numbered file is a second event, not a correction to the first.

    If the UIDs matched, importing both would leave Calendar showing only one.
    """
    first = make_uid(timed_spec)
    timed_spec.filename = "board-meeting-1"

    assert make_uid(timed_spec) != first
