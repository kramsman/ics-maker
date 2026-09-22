"""Turn raw spreadsheet rows into validated event specifications.

All of the defaulting rules (blank end time, blank filename, all-day
detection) and all of the per-row validation live here, so that writer.py
only ever receives events it can serialize without further checks.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

from ics_maker import constants
from ics_maker.sheet import RawRow, clean_str, coerce_bool, coerce_date, coerce_time


class RowError(Exception):
    """A problem with one spreadsheet row, reported against its row number."""

    def __init__(self, row_number: int, message: str) -> None:
        """Create a RowError.

        Args:
            row_number: 1-based sheet row the problem was found on.
            message: Human-readable description of the problem, without the
                "Row N:" prefix (that is added automatically).
        """
        super().__init__(f"Row {row_number}: {message}")
        self.row_number = row_number
        self.message = message


@dataclass
class EventSpec:
    """A fully resolved, validated event ready to be written as .ics.

    Attributes:
        start: Timezone-aware datetime, or a plain date for an all-day event.
        end: Exclusive end. For all-day events this is the day *after* the
            last day the event covers, per RFC 5545.
        reminder: How long before the start to fire an alarm, or None.
        filename: Output stem, without the .ics extension.
        row_number: Source row, used in error and summary messages.
    """

    title: str
    start: dt.datetime | dt.date
    end: dt.datetime | dt.date
    all_day: bool
    tzid: str
    filename: str
    row_number: int
    location: str = ""
    description: str = ""
    url: str = ""
    reminder: dt.timedelta | None = None


@cache
def _known_timezones() -> frozenset[str]:
    """Cache the IANA timezone name set; building it touches the filesystem."""
    return frozenset(available_timezones())


def parse_reminder(value: object, row_number: int) -> dt.timedelta | None:
    """Parse a reminder cell into a lead time before the event.

    Accepts "15m", "30 min", "1 hour", "2 hours", "1d", "1w", a bare number
    meaning minutes, and the web form's own phrasing ("15 minutes in advance").
    Blank, "none" or "no reminder" mean no alarm.

    Args:
        value: The raw Reminder cell value, or a timedelta if already parsed.
        row_number: 1-based sheet row, used to attribute a raised RowError.

    Returns:
        The lead time, or None for no alarm. timedelta(0) means the alarm
        fires exactly when the event starts.

    Raises:
        RowError: The cell holds text that is not a recognizable duration.
    """
    if isinstance(value, dt.timedelta):
        return value
    text = clean_str(value).lower()
    if text in constants.NO_REMINDER_VALUES:
        return None

    # Accept the wording used by the web form's dropdown.
    text = re.sub(r"\s*(in advance|before|prior)\s*$", "", text).strip()

    # <amount><unit>, e.g. "15m", "2.5 hours", or a bare number ("m" default).
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]*)", text)
    if match is None:
        raise RowError(
            row_number,
            f"{constants.COLUMNS['reminder']!r} is not a duration I recognize: "
            f"{clean_str(value)!r}. Try 15m, 1h, 2 hours, 1d, or leave it blank.",
        )

    amount, unit = match.groups()
    minutes_per_unit = constants.REMINDER_UNITS.get(unit or "m")
    if minutes_per_unit is None:
        raise RowError(
            row_number,
            f"{constants.COLUMNS['reminder']!r} has an unknown unit {unit!r} in "
            f"{clean_str(value)!r}. Use m, h, d or w.",
        )
    return dt.timedelta(minutes=float(amount) * minutes_per_unit)


def sanitize_filename(name: str) -> str:
    """Strip anything macOS, Windows or the shell would choke on.

    Generated files get carried between machines, so this clears the union of
    what those platforms forbid, not just what the local one does.

    Args:
        name: The raw Filename cell value, with or without a .ics extension.

    Returns:
        The cleaned filename stem, or "" if nothing usable survives, which
        lets the caller fall back to the row-numbered default.
    """
    name = name.removesuffix(".ics")
    cleaned = "".join(
        " " if ch in constants.ILLEGAL_FILENAME_CHARS else ch
        for ch in name
        if ch.isprintable()
    )
    cleaned = " ".join(cleaned.split())  # Collapse runs of whitespace.
    # Leading dots hide the file in Finder; trailing dots confuse some tools.
    cleaned = cleaned.strip(". ")[: constants.MAX_FILENAME_LENGTH].strip()

    # Windows reserves these for devices, and reserves them with any extension
    # attached -- so it is the part before the first dot that has to be judged,
    # and the part before the first dot that has to change. Appending to the
    # end instead would leave "CON.backup_", which Windows still refuses
    # because the segment before its first dot is still CON.
    head, dot, rest = cleaned.partition(".")
    if head.upper() in constants.WINDOWS_RESERVED_NAMES:
        # Reserved names are at most 4 characters, so this can never push the
        # result past MAX_FILENAME_LENGTH.
        cleaned = f"{head}{constants.RESERVED_NAME_SUFFIX}{dot}{rest}"

    return cleaned


def _resolve_timezone(row: RawRow, default_tzid: str) -> str:
    """Pick the row's timezone, falling back to the run default.

    Args:
        row: The spreadsheet row, checked for a Timezone column value.
        default_tzid: IANA timezone name to use when the row has none.

    Returns:
        The resolved IANA timezone name.

    Raises:
        RowError: The resolved name is not a known IANA timezone.
    """
    tzid = row.text("timezone") or default_tzid
    if tzid not in _known_timezones():
        raise RowError(
            row.row_number,
            f"{tzid!r} is not a known timezone name. Use an IANA name such as "
            f"America/New_York or Europe/Berlin.",
        )
    return tzid


def build_event(row: RawRow, default_tzid: str) -> EventSpec:
    """Validate one row and resolve every default into an EventSpec.

    Args:
        row: The raw spreadsheet row to validate.
        default_tzid: IANA timezone name to use when the row has no Timezone
            value of its own.

    Returns:
        A fully resolved EventSpec, ready to be written to .ics.

    Raises:
        RowError: The row is missing something required or holds a value that
            cannot be interpreted.
    """
    number = row.row_number

    title = row.text("title")
    if not title:
        raise RowError(number, f"{constants.COLUMNS['title']!r} is empty.")

    try:
        start_date = coerce_date(row.raw("start_date"), constants.COLUMNS["start_date"])
        end_date = coerce_date(row.raw("end_date"), constants.COLUMNS["end_date"])
        start_time = coerce_time(row.raw("start_time"), constants.COLUMNS["start_time"])
        end_time = coerce_time(row.raw("end_time"), constants.COLUMNS["end_time"])
        marked_all_day = coerce_bool(row.raw("all_day"), constants.COLUMNS["all_day"])
    except ValueError as exc:
        raise RowError(number, str(exc)) from exc

    if start_date is None:
        raise RowError(number, f"{constants.COLUMNS['start_date']!r} is empty.")

    tzid = _resolve_timezone(row, default_tzid)
    reminder = parse_reminder(row.raw("reminder"), number)

    # No start time is as good a signal as the checkbox that this is all-day.
    all_day = marked_all_day or start_time is None

    if all_day:
        last_day = end_date or start_date
        if last_day < start_date:
            raise RowError(
                number,
                f"{constants.COLUMNS['end_date']!r} ({last_day}) is before "
                f"{constants.COLUMNS['start_date']!r} ({start_date}).",
            )
        # RFC 5545 all-day DTEND is exclusive: a one-day event ends the *next*
        # day. Without this Apple Calendar shows the event a day short.
        start: dt.datetime | dt.date = start_date
        end: dt.datetime | dt.date = last_day + dt.timedelta(days=1)
    else:
        zone = ZoneInfo(tzid)
        start = dt.datetime.combine(start_date, start_time, tzinfo=zone)
        if end_time is None:
            end = dt.datetime.combine(
                end_date or start_date, start_time, tzinfo=zone
            ) + dt.timedelta(minutes=constants.DEFAULT_DURATION_MINUTES)
        else:
            end = dt.datetime.combine(end_date or start_date, end_time, tzinfo=zone)
        if end < start:
            raise RowError(
                number,
                f"the event ends ({end:%Y-%m-%d %H:%M}) before it starts "
                f"({start:%Y-%m-%d %H:%M}).",
            )

    filename = sanitize_filename(row.text("filename"))
    if not filename:
        filename = f"{constants.FILENAME_PREFIX}-{number}"

    return EventSpec(
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        tzid=tzid,
        filename=filename,
        row_number=number,
        location=row.text("location"),
        description=row.text("description"),
        url=row.text("url"),
        reminder=reminder,
    )


def build_events(
    rows: list[RawRow], default_tzid: str
) -> tuple[list[EventSpec], list[RowError]]:
    """Build every row, collecting failures instead of stopping at the first.

    Rows that name the same output file are rejected, because otherwise one
    row would silently overwrite another. Row-numbered default filenames are
    unique by construction, so this only ever catches a duplicated entry in
    the Filename column.

    Args:
        rows: The raw spreadsheet rows to validate, in sheet order.
        default_tzid: IANA timezone name to use for rows with no Timezone
            value of their own.

    Returns:
        The events that validated, and the errors for the rows that did not,
        both in sheet order.
    """
    events: list[EventSpec] = []
    errors: list[RowError] = []
    claimed: dict[str, int] = {}

    for row in rows:
        try:
            event = build_event(row, default_tzid)
        except RowError as exc:
            errors.append(exc)
            continue

        first_claim = claimed.get(event.filename.lower())
        if first_claim is not None:
            errors.append(
                RowError(
                    row.row_number,
                    f"{constants.COLUMNS['filename']!r} {event.filename!r} is "
                    f"already used by row {first_claim}. Filenames must be unique.",
                )
            )
            continue

        claimed[event.filename.lower()] = row.row_number
        events.append(event)

    return events, errors
