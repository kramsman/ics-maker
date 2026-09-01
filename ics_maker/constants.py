"""Defaults and schema definitions for ics-maker.

Everything a user is likely to want to change lives here rather than being
buried in argparse calls or scattered through the parsing modules.
"""

from pathlib import Path

# --- Run defaults -----------------------------------------------------------
#
# These are the values used when the matching command-line flag is not
# passed. Every one of them can be overridden per run without editing this
# file:
#   DEFAULT_TIMEZONE   -> --timezone TZID
#   DEFAULT_OUTPUT_DIR -> -o/--output-dir PATH
#   DEFAULT_INPUT_DIR  -> ignored once a spreadsheet path is given on the
#                         command line; only affects where the GUI file
#                         picker and --template start browsing/writing.

# IANA timezone name used for any row that leaves its Timezone column blank
# (see COLUMNS below). Must be a name zoneinfo recognizes, e.g.
# "America/New_York", "America/Los_Angeles", "Europe/London" -- not an
# abbreviation like "EST" and not a raw UTC offset like "-05:00".
DEFAULT_TIMEZONE: str = "America/New_York"

# Folder the generated .ics files are written into when --output-dir is not
# given. Created automatically if it does not already exist.
DEFAULT_OUTPUT_DIR = Path("~/Downloads/ics").expanduser()

# Folder the GUI file picker opens to when ics-maker is run with no
# spreadsheet argument, and the folder --template writes into when given no
# path of its own. Purely a starting point/convenience default -- you can
# always navigate elsewhere in the picker, or pass an explicit path on the
# command line.
DEFAULT_INPUT_DIR = Path("~/Downloads/ics").expanduser()
#     "/Users/Denise/Library/CloudStorage/Dropbox/PythonPrograms/ics-maker-root"

# Stem used for a generated file when its row's Filename column is left
# blank: row 7 with no Filename becomes "ics-7.ics" in the output folder.
FILENAME_PREFIX: str = "ics"

# How long a timed event runs when its row's End Time column is left blank.
# A 7:00 PM start with no End Time becomes 7:00-8:00 PM. Only affects timed
# events; an all-day event with no End Date simply spans the one Start Date.
DEFAULT_DURATION_MINUTES: int = 60

# Product identifier written into every generated file's PRODID line, as
# required by the .ics format. Not shown to the user in Calendar.
PRODID: str = "-//ics-maker//EN"

# Filename used by --template when it is passed no path of its own, or a
# directory instead of a filename (see resolve_template_path() in main.py).
TEMPLATE_FILENAME: str = "starter.xlsx"

# --- Spreadsheet schema ------------------------------------------------------
#
# COLUMNS defines every column ics-maker understands, and doubles as the
# exact header text written into the --template workbook. What each column
# means and what belongs in it:
#
#   Title        Required. The event's name (becomes the calendar entry's
#                title). A row with this blank is skipped and reported as an
#                error.
#   Location     Optional. Free text shown as the event's location.
#   Start Date   Required. A real Excel/Numbers date cell, or typed text in
#                one of the DATE_FORMATS below (e.g. 08/31/2026).
#   Start Time   Optional. A real time cell, or typed text in one of the
#                TIME_FORMATS below (e.g. 19:00 or 7:00 PM). Leaving this
#                blank makes the event all-day, whether or not All Day is
#                also checked.
#   End Date     Optional. Defaults to the same day as Start Date. For an
#                all-day event, this is the last day it covers (inclusive) --
#                a 3-day conference would have End Date two days after
#                Start Date, not three.
#   End Time     Optional. Defaults to Start Time plus DEFAULT_DURATION_MINUTES
#                above.
#   All Day      Optional. Accepts the words in TRUE_VALUES below (yes, y,
#                true, x, 1, "all day"); anything else, or blank, means no.
#                Redundant with leaving Start Time blank, but useful for
#                being explicit.
#   Description  Optional. Free text; becomes the event's Notes field in
#                Calendar (not shown on the calendar grid -- open the event
#                to see it). Line breaks are preserved.
#   Reminder     Optional. How long before the start to pop an alert, e.g.
#                15m, 1h, 2 hours, 1d, 1w, or a bare number of minutes.
#                See NO_REMINDER_VALUES and REMINDER_UNITS below for exactly
#                what is accepted. Blank means no alert at all.
#   Timezone     Optional. An IANA name (see DEFAULT_TIMEZONE above) used
#                for just this row, overriding --timezone for that one
#                event. Leave blank to use the run's default timezone.
#   URL          Optional. A web address Calendar shows as a clickable link
#                on the event.
#   Filename     Optional. The output file's name, without ".ics". Leave
#                blank to get FILENAME_PREFIX-<row number>.ics instead. Two
#                rows may not share the same Filename.
#
# Header matching when reading a spreadsheet is case-insensitive and ignores
# spaces, underscores, hyphens and periods, so "Start Date", "start_date"
# and "STARTDATE" all resolve to the same column -- you don't have to match
# the template's exact capitalization.
COLUMNS: dict[str, str] = {
    "title": "Title",
    "location": "Location",
    "start_date": "Start Date",
    "start_time": "Start Time",
    "end_date": "End Date",
    "end_time": "End Time",
    "all_day": "All Day",
    "description": "Description",
    "reminder": "Reminder",
    "timezone": "Timezone",
    "url": "URL",
    "filename": "Filename",
}

# Canonical field names (keys of COLUMNS) that read_rows() will refuse
# to proceed without.
REQUIRED_COLUMNS: tuple[str, ...] = ("title", "start_date")

# --- Value parsing ------------------------------------------------------------
#
# These control what a user may type into a cell when it is not a native
# Excel/Numbers date, time, or checkbox value.

# Accepted text formats for the Start Date / End Date columns, tried in
# order, e.g. "08/31/2026", "2026-08-31", "31.08.2026".
DATE_FORMATS: tuple[str, ...] = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d.%m.%Y", "%m-%d-%Y")

# Accepted text formats for the Start Time / End Time columns, tried in
# order, e.g. "19:00", "7:00 PM", "7PM".
TIME_FORMATS: tuple[str, ...] = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p")

# Text accepted in the All Day column to mean "yes" (case-insensitive).
# Anything not in here or FALSE_VALUES is a validation error rather than a
# silent guess.
TRUE_VALUES: frozenset[str] = frozenset(
    {"y", "yes", "true", "t", "x", "1", "all day", "allday"}
)
FALSE_VALUES: frozenset[str] = frozenset({"", "n", "no", "false", "f", "0"})

# Text accepted in the Reminder column to mean "no reminder at all" (as
# opposed to "0", which schedules an alert right at the event's start time,
# matching the web form's own "0 minutes in advance" option).
NO_REMINDER_VALUES: frozenset[str] = frozenset(
    {"", "none", "no", "no reminder", "n", "-"}
)

# Units accepted after a number in the Reminder column, mapped to how many
# minutes each one is worth -- e.g. "15m" -> 15, "2 hours" -> 120, "1d" ->
# 1440, "1w" -> 10080. A bare number with no unit ("45") is treated as
# minutes.
REMINDER_UNITS: dict[str, int] = {
    "m": 1,
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "h": 60,
    "hr": 60,
    "hrs": 60,
    "hour": 60,
    "hours": 60,
    "d": 60 * 24,
    "day": 60 * 24,
    "days": 60 * 24,
    "w": 60 * 24 * 7,
    "week": 60 * 24 * 7,
    "weeks": 60 * 24 * 7,
}

# Characters that must never appear in an output filename.
ILLEGAL_FILENAME_CHARS: str = '/\\:*?"<>|'
MAX_FILENAME_LENGTH: int = 100
