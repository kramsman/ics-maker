"""Tests for the form's Qt-free half.

These must never touch Qt: everything here imports ics_maker.form, which
deliberately keeps the widgets in form_dialog.py so that importing it does not
drag PySide6 (and a macOS dock icon) into the test run.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from ics_maker import constants
from ics_maker.event import RowError, build_event
from ics_maker.form import form_values_to_row, load_form_values, save_form_values
from ics_maker.sheet import coerce_date, coerce_time
from ics_maker.writer import write_event


def collected(**overrides):
    """Build the field dict the dialog's collect() would hand over."""
    values = {
        "title": "Dentist",
        "start_date": dt.date(2026, 3, 4),
        "end_date": dt.date(2026, 3, 4),
        "start_time": dt.time(9, 0),
        "end_time": dt.time(10, 0),
        "all_day": False,
        "reminder": "15m",
        "timezone": "America/New_York",
    }
    values.update(overrides)
    return values


def test_form_module_does_not_import_qt():
    """Importing the form must not pull PySide6 in behind it."""
    import sys

    import ics_maker.form  # noqa: F401

    assert "PySide6.QtWidgets" not in sys.modules


def test_a_filled_in_form_becomes_a_timed_event():
    spec = build_event(form_values_to_row(collected()), constants.DEFAULT_TIMEZONE)

    assert spec.title == "Dentist"
    assert not spec.all_day
    assert spec.start.hour == 9
    assert spec.end.hour == 10
    assert spec.reminder == dt.timedelta(minutes=15)
    # No Filename given, so the row-numbered default applies.
    assert spec.filename == f"{constants.FILENAME_PREFIX}-1"


def test_fields_the_form_left_blank_are_read_as_empty_cells():
    """Keys absent from the dict must behave exactly like an empty cell."""
    row = form_values_to_row({"title": "Lunch", "start_date": dt.date(2026, 3, 4)})

    assert set(row.values) == set(constants.COLUMNS)
    assert row.text("location") == ""
    assert row.raw("end_time") is None


def test_all_day_gets_an_exclusive_next_day_end():
    """The all-day rule must match the spreadsheet path's, per RFC 5545."""
    values = collected(all_day=True, start_time=None, end_time=None)

    spec = build_event(form_values_to_row(values), constants.DEFAULT_TIMEZONE)

    assert spec.all_day
    assert spec.start == dt.date(2026, 3, 4)
    assert spec.end == dt.date(2026, 3, 5)


def test_a_blank_title_is_rejected_rather_than_written():
    with pytest.raises(RowError) as excinfo:
        build_event(form_values_to_row(collected(title="  ")), constants.DEFAULT_TIMEZONE)

    # The dialog shows .message, so that is what has to read sensibly.
    assert constants.COLUMNS["title"] in excinfo.value.message


def test_an_end_before_the_start_is_rejected():
    values = collected(start_time=dt.time(17, 0), end_time=dt.time(9, 0))

    with pytest.raises(RowError):
        build_event(form_values_to_row(values), constants.DEFAULT_TIMEZONE)


def test_the_reminder_dropdown_wording_parses():
    """Every choice the dropdown offers must be one parse_reminder accepts."""
    from ics_maker.form import REMINDER_CHOICES

    for choice in REMINDER_CHOICES:
        build_event(
            form_values_to_row(collected(reminder=choice)), constants.DEFAULT_TIMEZONE
        )


def test_a_form_event_writes_a_usable_ics_file(tmp_path):
    spec = build_event(
        form_values_to_row(collected(filename="dentist")), constants.DEFAULT_TIMEZONE
    )

    path = write_event(spec, tmp_path)

    text = path.read_bytes().decode()
    assert path.name == "dentist.ics"
    assert "SUMMARY:Dentist" in text
    assert "TZID=America/New_York" in text
    assert "BEGIN:VALARM" in text


# --- remembering the last event ---------------------------------------------


def test_saved_values_round_trip_back_through_build_event(tmp_path):
    """What comes back out must still build the same event it went in as."""
    state = tmp_path / "last-event.json"
    values = collected(title="Book club", location="Library")

    save_form_values(values, state)
    restored = load_form_values(state)

    spec = build_event(form_values_to_row(restored), constants.DEFAULT_TIMEZONE)
    assert spec.title == "Book club"
    assert spec.location == "Library"
    assert spec.start == dt.datetime(
        2026, 3, 4, 9, 0, tzinfo=ZoneInfo("America/New_York")
    )
    assert spec.reminder == dt.timedelta(minutes=15)


def test_dates_and_times_survive_as_iso_text(tmp_path):
    """They are stored as text the existing coerce_* helpers already parse."""
    state = tmp_path / "last-event.json"

    save_form_values(collected(), state)

    stored = json.loads(state.read_text())
    assert stored["start_date"] == "2026-03-04"
    assert stored["start_time"] == "09:00:00"
    assert coerce_date(stored["start_date"], "Start Date") == dt.date(2026, 3, 4)
    assert coerce_time(stored["start_time"], "Start Time") == dt.time(9, 0)


def test_an_all_day_event_comes_back_all_day(tmp_path):
    state = tmp_path / "last-event.json"

    save_form_values(collected(all_day=True, start_time=None, end_time=None), state)
    restored = load_form_values(state)

    assert restored["start_time"] is None
    spec = build_event(form_values_to_row(restored), constants.DEFAULT_TIMEZONE)
    assert spec.all_day


def test_nothing_saved_yet_is_not_an_error(tmp_path):
    assert load_form_values(tmp_path / "nope.json") == {}


def test_a_corrupt_state_file_opens_a_blank_form(tmp_path):
    """A bad file must never wedge the form shut; it just means 'nothing saved'."""
    state = tmp_path / "last-event.json"
    state.write_text("{not json at all")

    assert load_form_values(state) == {}


def test_a_state_file_holding_the_wrong_shape_is_ignored(tmp_path):
    state = tmp_path / "last-event.json"
    state.write_text('["a", "list", "not", "an", "object"]')

    assert load_form_values(state) == {}


def test_unknown_keys_in_the_state_file_are_dropped(tmp_path):
    """A stale file from another version must not inject keys into the RawRow."""
    state = tmp_path / "last-event.json"
    state.write_text('{"title": "Kept", "attendees": "dropped"}')

    restored = load_form_values(state)

    assert restored == {"title": "Kept"}
    assert set(form_values_to_row(restored).values) == set(constants.COLUMNS)


def test_saving_survives_an_unwritable_location(tmp_path):
    """Losing the state file must never cost the user the event they just saved."""
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("in the way")

    save_form_values(collected(), blocked / "last-event.json")  # must not raise


# --- the run_form loop -------------------------------------------------------


def run_form_with(monkeypatch, tmp_path, specs, state=None):
    """Drive main.run_form() with the window and prompts stubbed out.

    Both stubs go in via sys.modules, because run_form imports them inside the
    function body -- and importing the real uvbekutils.confirm would pull Qt in
    behind it, which the tests in this file must not do.

    Args:
        specs: The EventSpecs the stubbed form "returns", one per iteration.
            A trailing None stands for the user cancelling.
        state: Ignored; present so callers read symmetrically.

    Returns:
        The exit code run_form() returned.
    """
    import sys
    import types

    from ics_maker import main

    queue = list(specs)
    answers = ["add another"] * (len(queue) - 1) + ["done"]

    fake_uvbekutils = types.ModuleType("uvbekutils")
    fake_uvbekutils.confirm = lambda *a, **k: answers.pop(0) if answers else "done"
    monkeypatch.setitem(sys.modules, "uvbekutils", fake_uvbekutils)
    monkeypatch.setattr(
        "ics_maker.form.show_event_form", lambda tz: queue.pop(0) if queue else None
    )

    args = main.build_parser().parse_args(
        ["--form", "-o", str(tmp_path), "--timezone", "America/New_York"]
    )
    return main.run_form(args)


def spec_named(filename, title="Book club"):
    return build_event(
        form_values_to_row(collected(title=title, filename=filename)),
        constants.DEFAULT_TIMEZONE,
    )


def test_two_form_events_sharing_a_name_do_not_overwrite(monkeypatch, tmp_path):
    """The window reopens holding the old Filename; neither event may be lost."""
    specs = [spec_named("book-club", "Book club"), spec_named("book-club", "Poker")]

    assert run_form_with(monkeypatch, tmp_path, specs) == 0

    written = sorted(p.name for p in tmp_path.glob("*.ics"))
    assert written == ["book-club-1.ics", "book-club.ics"]
    assert "Poker" in (tmp_path / "book-club-1.ics").read_bytes().decode()


def test_a_form_event_numbers_around_files_from_an_earlier_launch(monkeypatch, tmp_path):
    (tmp_path / "book-club.ics").touch()

    run_form_with(monkeypatch, tmp_path, [spec_named("book-club")])

    assert (tmp_path / "book-club-1.ics").is_file()


def test_cancelling_the_first_form_writes_nothing(monkeypatch, tmp_path):
    assert run_form_with(monkeypatch, tmp_path, [None]) == 0
    assert list(tmp_path.glob("*.ics")) == []


def test_a_bad_timezone_stops_before_the_window_opens(tmp_path):
    from ics_maker import main

    args = main.build_parser().parse_args(
        ["--form", "-o", str(tmp_path), "--timezone", "Mars/Olympus"]
    )

    assert main.run_form(args) == 2
    assert list(tmp_path.glob("*.ics")) == []
