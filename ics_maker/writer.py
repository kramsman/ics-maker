"""Serialize EventSpecs to .ics files that Apple Calendar accepts.

Each row becomes its own single-event VCALENDAR. The icalendar library
handles the fiddly parts of RFC 5545 for us: CRLF line endings, folding lines
at 75 octets, and escaping commas, semicolons and newlines inside
DESCRIPTION.
"""

from __future__ import annotations

import datetime as dt
import uuid
from functools import lru_cache
from pathlib import Path

from icalendar import Alarm, Calendar, Event, Timezone

from ics_maker import constants
from ics_maker.event import EventSpec

# Namespace for deterministic UIDs. Any fixed UUID works; this one is arbitrary
# but must never change, or previously generated events would lose their
# identity and re-import as duplicates.
_UID_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


@lru_cache(maxsize=None)
def _vtimezone(tzid: str, year: int) -> Timezone:
    """Build a VTIMEZONE covering the years around ``year``.

    Apple Calendar is unreliable with a bare TZID that has no accompanying
    VTIMEZONE definition, so every timed event carries one. The default date
    span runs 1970-2038 and emits ~50 lines of RDATEs; narrowing it to a few
    years around the event keeps the file small while still covering it.

    icalendar's own docs note this call is slow and ask that results be
    cached, hence the memoization.

    Args:
        tzid: IANA timezone name, e.g. "America/New_York".
        year: The event's year; the VTIMEZONE spans a few years either side.

    Returns:
        A Timezone component ready to embed in the VCALENDAR.
    """
    return Timezone.from_tzid(
        tzid,
        first_date=dt.date(year - 1, 1, 1),
        last_date=dt.date(year + 3, 1, 1),
    )


def make_uid(spec: EventSpec) -> str:
    """Derive a UID that stays the same every time this row is regenerated.

    A stable UID means re-importing a corrected file updates the existing
    event in Calendar instead of creating a second copy of it.

    Args:
        spec: The event to derive a UID for.

    Returns:
        A UID string, stable across runs as long as filename, title and
        start time are unchanged.
    """
    seed = f"{spec.filename}|{spec.title}|{spec.start.isoformat()}"
    return f"{uuid.uuid5(_UID_NAMESPACE, seed)}@ics-maker"


def build_calendar(spec: EventSpec, now: dt.datetime | None = None) -> Calendar:
    """Wrap a single event in a VCALENDAR.

    Args:
        spec: The event to serialize.
        now: Timestamp to record as DTSTAMP; defaults to the current UTC
            time. Exposed as a parameter mainly so tests can pin it.

    Returns:
        A Calendar component containing the VTIMEZONE (for timed events) and
        the VEVENT, ready to be serialized with ``.to_ical()``.
    """
    calendar = Calendar()
    calendar.add("prodid", constants.PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    # PUBLISH tells Calendar this is an event to add, not a meeting invitation
    # it should offer to accept or decline.
    calendar.add("method", "PUBLISH")

    if not spec.all_day:
        calendar.add_component(_vtimezone(spec.tzid, spec.start.year))

    event = Event()
    event.add("uid", make_uid(spec))
    event.add("dtstamp", now or dt.datetime.now(dt.UTC))
    event.add("summary", spec.title)
    # For all-day events these are plain dates, which icalendar renders as
    # DTSTART;VALUE=DATE with no timezone attached.
    event.add("dtstart", spec.start)
    event.add("dtend", spec.end)

    if spec.location:
        event.add("location", spec.location)
    if spec.description:
        event.add("description", spec.description)
    if spec.url:
        event.add("url", spec.url)

    if spec.reminder is not None:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", spec.title)
        # A negative trigger means "before the start"; zero fires at start.
        alarm.add("trigger", -spec.reminder)
        event.add_component(alarm)

    calendar.add_component(event)
    return calendar


def write_event(spec: EventSpec, output_dir: Path) -> Path:
    """Write one event to ``<output_dir>/<spec.filename>.ics``.

    An existing file of the same name is overwritten, so re-running the same
    spreadsheet cleanly replaces its previous output.

    Args:
        spec: The event to write.
        output_dir: Directory to write into; must already exist.

    Returns:
        The path that was written.
    """
    path = output_dir / f"{spec.filename}.ics"
    # Binary mode on purpose: text mode would translate the CRLF line endings
    # that RFC 5545 requires.
    path.write_bytes(build_calendar(spec).to_ical())
    return path
