#!/bin/sh
# Double-click this in Finder to open the new-event form.
#
# The project path is absolute so this file works from anywhere -- copy it to
# the Desktop, drag it to the Dock, put it in ~/Applications. Finder launches a
# .command with an unpredictable working directory, so relying on the script's
# own location would break the moment it was moved.
exec /Users/Denise/.local/bin/uv run \
    --project "/Users/Denise/Library/CloudStorage/Dropbox/PythonPrograms/ics-maker-root" \
    ics-maker --form
