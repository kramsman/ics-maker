"""A one-event GUI form, as an alternative to filling in a spreadsheet.

The form deliberately produces a :class:`~ics_maker.sheet.RawRow` and hands it
to :func:`~ics_maker.event.build_event`, rather than assembling an EventSpec
itself. Every defaulting and validation rule therefore comes from the same
place the spreadsheet path uses, and the two cannot drift apart.

Nothing in this module imports Qt. The widgets live in form_dialog.py, which
show_event_form() imports only when a window is actually wanted -- the same
discipline main.pick_spreadsheet() follows, and for the same reason: touching
PySide6 turns a plain terminal run into a windowed macOS app with a dock icon.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ics_maker import constants
from ics_maker.event import EventSpec
from ics_maker.sheet import RawRow

# Offered in the Reminder dropdown. The box stays editable, so anything
# parse_reminder() accepts ("45", "2 hours", "1w") can still be typed in.
REMINDER_CHOICES: tuple[str, ...] = (
    "none", "0m", "5m", "15m", "30m", "1h", "2h", "1d", "1w",
)

# The form only ever describes one event, so its "row" is always row 1. That
# number surfaces in a RowError as "Row 1:", which the dialog strips before
# showing the message (it uses RowError.message, not str(exc)).
FORM_ROW_NUMBER: int = 1


def form_values_to_row(values: dict[str, object]) -> RawRow:
    """Map form field values onto a RawRow keyed by canonical field name.

    The coerce_* helpers in sheet.py already accept native ``date``, ``time``
    and ``bool`` objects, so Qt's ``QDate.toPython()`` / ``QTime.toPython()``
    results pass straight through without conversion here.

    Args:
        values: Field values keyed by the canonical names in
            ``constants.COLUMNS``. Missing keys and None values are treated as
            blank cells, exactly as an empty spreadsheet cell would be.

    Returns:
        A RawRow ready for build_event().
    """
    return RawRow(
        row_number=FORM_ROW_NUMBER,
        values={name: values.get(name) for name in constants.COLUMNS},
    )


def save_form_values(
    values: dict[str, object], path: Path = constants.FORM_STATE_FILE
) -> None:
    """Remember a form submission so the next form can open prefilled.

    Dates and times are stored in ISO format, which is one of the text formats
    ``constants.DATE_FORMATS``/``TIME_FORMATS`` already accept -- so loading
    them back needs no parsing code of its own (see load_form_values).

    Writing is best-effort: a read-only or unwritable config directory must
    never cost the user the event they just saved.

    Args:
        values: The field values to remember, keyed by canonical field name.
        path: Where to write; defaults to ``constants.FORM_STATE_FILE``.
    """
    encoded = {
        name: value.isoformat() if isinstance(value, (dt.date, dt.time)) else value
        for name, value in values.items()
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(encoded, indent=2))
    except OSError:
        pass


def load_form_values(path: Path = constants.FORM_STATE_FILE) -> dict[str, object]:
    """Read back the last saved form submission.

    Dates and times come back as the ISO strings save_form_values wrote, not
    as date/time objects; the caller converts them with sheet.coerce_date and
    sheet.coerce_time, which accept that format already.

    Args:
        path: Where to read from; defaults to ``constants.FORM_STATE_FILE``.

    Returns:
        The remembered values, or an empty dict when there is nothing saved or
        the file cannot be read. A corrupt file is treated as "nothing saved"
        rather than an error, so a bad write can never wedge the form shut.
    """
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    # Ignore anything that is not a field the form knows about, so a stale file
    # from an older version cannot inject unexpected keys into the RawRow.
    return {name: loaded[name] for name in constants.COLUMNS if name in loaded}


def show_event_form(default_tzid: str = constants.DEFAULT_TIMEZONE) -> EventSpec | None:
    """Open the form and return the validated event, or None if cancelled.

    Validation happens inside the dialog, so a bad field keeps the window open
    with the problem shown inline and the user never loses what they typed.

    Args:
        default_tzid: IANA timezone name to preselect in the Timezone box.

    Returns:
        The validated EventSpec, or None if the user cancelled.
    """
    from ics_maker.form_dialog import run_dialog

    return run_dialog(default_tzid)
