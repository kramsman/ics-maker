"""The PySide6 window behind ``ics-maker --form``.

Importing this module imports Qt, which on macOS is enough to give the process
a dock icon and steal keyboard focus. Import it only when a window is actually
wanted; ics_maker.form.show_event_form() is the intended entry point.
"""

from __future__ import annotations

import sys
from zoneinfo import available_timezones

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTimeEdit,
    QVBoxLayout,
)

from ics_maker import constants
from ics_maker.event import EventSpec, RowError, build_event
from ics_maker.form import (
    REMINDER_CHOICES,
    form_values_to_row,
    load_form_values,
    save_form_values,
)
from ics_maker.sheet import coerce_bool, coerce_date, coerce_time


def run_dialog(default_tzid: str) -> EventSpec | None:
    """Show the form modally and return the validated event, or None.

    Args:
        default_tzid: IANA timezone name to preselect when nothing was saved
            from a previous run.

    Returns:
        The validated EventSpec, or None if the user cancelled.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    dialog = EventFormDialog(default_tzid)
    if dialog.exec() == QDialog.Accepted:
        return dialog.event_spec
    return None


class EventFormDialog(QDialog):
    """One event's worth of fields, validated on Save.

    The window opens prefilled with whatever was saved last (see
    ics_maker.form.load_form_values), so making a near-duplicate event is a
    matter of changing the title and the date. Clear blanks it back out.

    Attributes:
        event_spec: The validated event, set only once Save succeeds.
    """

    def __init__(self, default_tzid: str) -> None:
        """Build the form and fill it in from the last saved event.

        Args:
            default_tzid: IANA timezone name to preselect when nothing was
                saved from a previous run.
        """
        super().__init__()
        self.setWindowTitle("New calendar event")
        self.event_spec: EventSpec | None = None
        self.default_tzid = default_tzid

        # While these are True the End field mirrors its Start counterpart.
        # Touching an End field by hand clears the flag and stops the mirroring.
        self._end_date_follows = True
        self._end_time_follows = True
        # Set True around programmatic writes so the values we fill in
        # ourselves are not mistaken for the user editing an End field.
        self._syncing = False

        self._build_widgets()
        self._build_layout()
        self._connect_signals()
        self.apply_values(load_form_values())

    # --- construction --------------------------------------------------------

    def _build_widgets(self) -> None:
        """Create every field widget. Values are filled in by apply_values()."""
        self.title = QLineEdit()
        self.title.setPlaceholderText("required")
        self.location = QLineEdit()

        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)

        self.start_time = QTimeEdit()
        self.end_time = QTimeEdit()

        self.all_day = QCheckBox("All day (no start or end time)")

        self.description = QPlainTextEdit()
        self.description.setFixedHeight(80)

        self.reminder = QComboBox()
        self.reminder.setEditable(True)
        self.reminder.addItems(REMINDER_CHOICES)

        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        self.timezone.addItems(sorted(available_timezones()))

        self.url = QLineEdit()
        self.filename = QLineEdit()
        self.filename.setPlaceholderText("optional; blank uses the title's row default")

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet("color: #b00020;")
        self.problem.hide()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Reset | QDialogButtonBox.Cancel
        )
        # "Clear" says what it does here; "Reset" would suggest going back to
        # the saved event, which is what the form already opens showing.
        self.buttons.button(QDialogButtonBox.Reset).setText("Clear")
        # Nothing useful can be built without a title, so the button stays off
        # until there is one rather than failing validation on every empty form.
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)

    def _build_layout(self) -> None:
        """Arrange the widgets in a label/field form."""
        form = QFormLayout()
        form.addRow(constants.COLUMNS["title"], self.title)
        form.addRow(constants.COLUMNS["location"], self.location)
        form.addRow(self.all_day)
        form.addRow(constants.COLUMNS["start_date"], self.start_date)
        form.addRow(constants.COLUMNS["start_time"], self.start_time)
        form.addRow(constants.COLUMNS["end_date"], self.end_date)
        form.addRow(constants.COLUMNS["end_time"], self.end_time)
        form.addRow(constants.COLUMNS["reminder"], self.reminder)
        form.addRow(constants.COLUMNS["timezone"], self.timezone)
        form.addRow(constants.COLUMNS["description"], self.description)
        form.addRow(constants.COLUMNS["url"], self.url)
        form.addRow(constants.COLUMNS["filename"], self.filename)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)

    def _connect_signals(self) -> None:
        """Wire up validation, the all-day toggle, and the Start/End mirroring."""
        self.title.textChanged.connect(self.on_title_changed)
        self.all_day.toggled.connect(self.on_all_day_toggled)
        self.start_date.dateChanged.connect(self.on_start_date_changed)
        self.end_date.dateChanged.connect(self.on_end_date_changed)
        self.start_time.timeChanged.connect(self.on_start_time_changed)
        self.end_time.timeChanged.connect(self.on_end_time_changed)
        self.buttons.accepted.connect(self.on_save)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Reset).clicked.connect(self.on_clear)

    # --- filling in ----------------------------------------------------------

    def apply_values(self, values: dict[str, object]) -> None:
        """Fill every field from a values dict, defaulting whatever is missing.

        Used both to restore the last saved event and, with an empty dict, to
        implement Clear. Values may be the ISO strings load_form_values()
        returns or real date/time objects; the sheet.coerce_* helpers take
        either, so a hand-edited state file still loads.

        Args:
            values: Field values keyed by canonical field name. Anything
                missing, blank, or unparseable falls back to its default.
        """
        self._syncing = True  # Filling in fields is not the user editing them.
        try:
            self.title.setText(_as_text(values.get("title")))
            self.location.setText(_as_text(values.get("location")))
            self.description.setPlainText(_as_text(values.get("description")))
            self.url.setText(_as_text(values.get("url")))
            self.filename.setText(_as_text(values.get("filename")))

            self.all_day.setChecked(_as_bool(values.get("all_day")))

            start_date = _as_date(values.get("start_date")) or QDate.currentDate()
            self.start_date.setDate(start_date)
            self.end_date.setDate(_as_date(values.get("end_date")) or start_date)

            start_time = _as_time(values.get("start_time")) or _next_hour()
            self.start_time.setTime(start_time)
            self.end_time.setTime(
                _as_time(values.get("end_time")) or _after(start_time)
            )

            self.reminder.setCurrentText(_as_text(values.get("reminder")) or "none")
            self.timezone.setCurrentText(
                _as_text(values.get("timezone")) or self.default_tzid
            )

            self.problem.hide()
        finally:
            self._syncing = False

        # Only resume mirroring if the restored End values are exactly what the
        # mirroring would have produced; otherwise the user set them by hand
        # last time and editing Start must not silently overwrite them again.
        self._end_date_follows = self.end_date.date() == self.start_date.date()
        self._end_time_follows = self.end_time.time() == _after(self.start_time.time())
        self._sync_time_fields()
        self.on_title_changed(self.title.text())

    # --- interaction ---------------------------------------------------------

    def on_title_changed(self, text: str) -> None:
        """Enable Save only once the required Title has something in it."""
        self.buttons.button(QDialogButtonBox.Save).setEnabled(bool(text.strip()))

    def on_all_day_toggled(self, checked: bool) -> None:
        """Grey out the time fields when the event covers whole days."""
        self._sync_time_fields()

    def _sync_time_fields(self) -> None:
        """Enable or disable the time fields to match the All Day checkbox."""
        enabled = not self.all_day.isChecked()
        self.start_time.setEnabled(enabled)
        self.end_time.setEnabled(enabled)

    def on_start_date_changed(self, value: QDate) -> None:
        """Drag the End Date along with the Start Date until it is edited."""
        if self._end_date_follows:
            self._set_quietly(self.end_date.setDate, value)

    def on_end_date_changed(self, value: QDate) -> None:
        """Stop mirroring once the user sets an End Date of their own."""
        if not self._syncing:
            self._end_date_follows = False

    def on_start_time_changed(self, value: QTime) -> None:
        """Keep End Time a default duration after Start Time until it is edited."""
        if self._end_time_follows:
            self._set_quietly(self.end_time.setTime, _after(value))

    def on_end_time_changed(self, value: QTime) -> None:
        """Stop mirroring once the user sets an End Time of their own."""
        if not self._syncing:
            self._end_time_follows = False

    def on_clear(self) -> None:
        """Blank the form back to its defaults, leaving the saved event alone.

        The state file is untouched: reopening the window still brings back the
        last saved event, so Clear cannot lose anything permanently.
        """
        self.apply_values({})

    def _set_quietly(self, setter, value) -> None:
        """Write a widget value without it counting as a user edit.

        Qt fires dateChanged/timeChanged for programmatic writes just as it
        does for typed ones, so the mirroring we do here would otherwise
        immediately cancel itself.

        Args:
            setter: The widget setter to call, e.g. ``self.end_date.setDate``.
            value: The value to pass to it.
        """
        self._syncing = True
        try:
            setter(value)
        finally:
            self._syncing = False

    # --- saving --------------------------------------------------------------

    def collect(self) -> dict[str, object]:
        """Read every field into the canonical field-name dict build_event wants.

        Returns:
            Field values keyed by the canonical names in ``constants.COLUMNS``,
            with blank optional fields left as None so they read as empty cells.
        """
        all_day = self.all_day.isChecked()
        return {
            "title": self.title.text(),
            "location": self.location.text(),
            "start_date": self.start_date.date().toPython(),
            "end_date": self.end_date.date().toPython(),
            # None rather than a time makes build_event() treat this as
            # all-day, which is the same signal a blank spreadsheet cell gives.
            "start_time": None if all_day else self.start_time.time().toPython(),
            "end_time": None if all_day else self.end_time.time().toPython(),
            "all_day": all_day,
            "description": self.description.toPlainText(),
            "reminder": self.reminder.currentText(),
            "timezone": self.timezone.currentText(),
            "url": self.url.text(),
            "filename": self.filename.text(),
        }

    def on_save(self) -> None:
        """Validate the form, keeping the window open if anything is wrong."""
        values = self.collect()
        row = form_values_to_row(values)
        try:
            self.event_spec = build_event(row, self.default_tzid)
        except RowError as exc:
            # exc.message, not str(exc): the latter is prefixed "Row 1:", which
            # means nothing to someone looking at a form.
            self.problem.setText(exc.message)
            self.problem.show()
            return
        # Only remember an event that actually validated, so a half-finished
        # attempt never comes back to greet the next run.
        save_form_values(values)
        self.accept()


# --- value conversion --------------------------------------------------------
#
# Restored values arrive as the ISO strings save_form_values() wrote. The
# sheet.coerce_* helpers already parse that format, so these wrappers only add
# the "fall back to the default instead of raising" behaviour a form needs: a
# stale or hand-edited state file must never stop the window from opening.


def _as_text(value: object) -> str:
    """Return a restored value as text, or "" when it is missing."""
    return "" if value is None else str(value)


def _as_bool(value: object) -> bool:
    """Return a restored value as a bool, or False when it is unreadable."""
    try:
        return coerce_bool(value, "All Day")
    except ValueError:
        return False


def _as_date(value: object) -> QDate | None:
    """Return a restored value as a QDate, or None when it is unreadable."""
    try:
        parsed = coerce_date(value, "Start Date")
    except ValueError:
        return None
    return QDate(parsed) if parsed is not None else None


def _as_time(value: object) -> QTime | None:
    """Return a restored value as a QTime, or None when it is unreadable."""
    try:
        parsed = coerce_time(value, "Start Time")
    except ValueError:
        return None
    return QTime(parsed) if parsed is not None else None


def _next_hour() -> QTime:
    """The upcoming whole hour: the default start time for a fresh form."""
    upcoming = QTime.currentTime().addSecs(3600)
    return QTime(upcoming.hour(), 0)


def _after(start: QTime) -> QTime:
    """The default end time for an event starting at ``start``."""
    return start.addSecs(constants.DEFAULT_DURATION_MINUTES * 60)
