"""Command line entry point for ics-maker.

    ics-maker                   # pick a spreadsheet with the GUI file picker
    ics-maker events.xlsx       # skip the picker
    ics-maker --template        # write a starter spreadsheet to fill in
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zoneinfo import available_timezones

from ics_maker import constants
from ics_maker.event import build_events
from ics_maker.sheet import SheetError, read_rows
from ics_maker.template import write_template
from ics_maker.writer import write_event


def build_parser() -> argparse.ArgumentParser:
    """Define the command line interface."""
    parser = argparse.ArgumentParser(
        prog="ics-maker",
        description=(
            "Turn a spreadsheet of events into one .ics calendar file per row. "
            "With no spreadsheet given, a file picker opens."
        ),
    )
    parser.add_argument(
        "spreadsheet",
        nargs="?",
        type=Path,
        help=f"the .xlsx file to read (default: pick one from {constants.DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=constants.DEFAULT_OUTPUT_DIR,
        help=f"where to write the .ics files (default: {constants.DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--timezone",
        default=constants.DEFAULT_TIMEZONE,
        help=(
            "IANA timezone for rows without a Timezone column "
            f"(default: {constants.DEFAULT_TIMEZONE})"
        ),
    )
    parser.add_argument(
        "--sheet",
        help="worksheet name to read (default: the workbook's active sheet)",
    )
    parser.add_argument(
        "--template",
        # nargs="?" + const="" lets --template be passed bare (args.template
        # becomes "") or with a path; omitting the flag entirely leaves
        # args.template as None, which is how run() tells "write a template"
        # apart from "generate .ics files".
        nargs="?",
        const="",
        metavar="PATH",
        help=(
            "write a starter spreadsheet and exit "
            f"(default: {constants.DEFAULT_INPUT_DIR / constants.TEMPLATE_FILENAME})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the spreadsheet and report what would be written, without writing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="write nothing if any row has a problem (default: write the good rows)",
    )
    return parser


def resolve_template_path(raw: str) -> Path:
    """Work out where --template should write.

    An empty string means the flag was passed with no value; a directory means
    "put the default filename in here".

    Args:
        raw: The --template argument value: "" (bare flag), a directory, or
            a file path with or without a .xlsx extension.

    Returns:
        The resolved .xlsx path to write the template to.
    """
    if not raw:
        return constants.DEFAULT_INPUT_DIR / constants.TEMPLATE_FILENAME
    path = Path(raw).expanduser()
    if path.is_dir():
        return path / constants.TEMPLATE_FILENAME
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    return path


def pick_spreadsheet() -> Path | None:
    """Open the GUI picker and return the chosen file, or None if cancelled.

    The import is deliberately local: uvbekutils resolves its names lazily so
    that Qt is only loaded when a dialog is actually needed. Importing
    select_file at module scope would turn every --template or explicit-path
    run into a windowed macOS app that takes a dock icon and steals focus.

    Returns:
        The chosen file's path, or None if the user cancelled the dialog.
    """
    from uvbekutils import select_file

    start_dir = constants.DEFAULT_INPUT_DIR
    if not start_dir.is_dir():
        start_dir = Path.home()

    chosen = select_file(
        title="Select the events spreadsheet",
        start_dir=str(start_dir),
        files_like="*.xlsx",
        mode="file",
        title2="Each row in the sheet becomes one .ics calendar file.",
        show_sortbutton=True,
    )
    return Path(chosen) if chosen else None


def run(args: argparse.Namespace) -> int:
    """Read the spreadsheet, write the .ics files, and report what happened.

    Args:
        args: Parsed CLI arguments from build_parser(), excluding --template
            (that flag is handled by main() before run() is ever called).

    Returns:
        A process exit code:
            0: every row was written (or the user cancelled the picker, or
                a header-only sheet had nothing to do).
            1: at least one row was skipped due to a validation problem.
            2: a setup problem prevented reading the spreadsheet at all
                (bad --timezone, missing file, missing/bad --sheet).
    """
    if args.timezone not in available_timezones():
        print(
            f"error: {args.timezone!r} is not a known timezone name. "
            f"Use an IANA name such as America/New_York.",
            file=sys.stderr,
        )
        return 2

    spreadsheet = args.spreadsheet
    if spreadsheet is None:
        spreadsheet = pick_spreadsheet()
        if spreadsheet is None:
            print("Cancelled; nothing was written.")
            return 0

    spreadsheet = spreadsheet.expanduser()
    if not spreadsheet.is_file():
        print(f"error: no such file: {spreadsheet}", file=sys.stderr)
        return 2

    try:
        rows = read_rows(spreadsheet, args.sheet)
    except SheetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not rows:
        print(f"{spreadsheet.name} has a header row but no events.")
        return 0

    events, errors = build_events(rows, args.timezone)

    if errors and args.strict:
        print(f"error: {len(errors)} row(s) have problems; wrote nothing (--strict).",
              file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    output_dir = args.output_dir.expanduser()
    if args.dry_run:
        print(f"Dry run: would write {len(events)} file(s) to {output_dir}")
        for event in events:
            print(f"  {event.filename}.ics  <- row {event.row_number}: {event.title}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        for event in events:
            write_event(event, output_dir)
        print(f"Wrote {len(events)} file(s) to {output_dir}")

    if errors:
        # Flush first: stdout is block-buffered when piped, stderr is not, so
        # without this the summary would appear after the error list.
        sys.stdout.flush()
        print(f"Skipped {len(errors)} row(s):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    """Parse arguments and dispatch.

    Handles --template itself (writing the workbook and exiting) before
    handing everything else off to run().

    Returns:
        A process exit code; see run() for what each value means.
    """
    args = build_parser().parse_args()

    if args.template is not None:
        path = write_template(resolve_template_path(args.template))
        print(f"Wrote template to {path}")
        print("Fill it in, then run: ics-maker")
        return 0

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
