"""History logging for Novato.

Per safety rule #6, *every executed command* is logged to
``~/.novato/history.log`` with a timestamp. The log is append-only, plain text,
and easy to audit:

    2026-06-10T14:03:21+00:00  EXEC    sudo pacman -S shotcut
    2026-06-10T14:05:02+00:00  DRYRUN  sudo apt install vlc
    2026-06-10T14:06:10+00:00  FIX     sudo pacman -S vlc

Logging never raises into the caller: a tool that cannot write its history log
should still help the user, so failures are swallowed (and optionally surfaced
elsewhere). Nothing sensitive beyond the command itself is recorded.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

from .config import config_dir, ensure_config_dir

LOG_FILENAME = "history.log"

# Event kinds used across Novato. Kept short and fixed-width-friendly.
EVENT_EXEC = "EXEC"      # A real command was executed.
EVENT_DRYRUN = "DRYRUN"  # Command shown but skipped due to --dry-run.
EVENT_FIX = "FIX"        # A /mistake fix was executed.
EVENT_DECLINE = "DECLINE"  # User declined a confirmation prompt.
EVENT_SEARCH = "SEARCH"  # An intent search was performed.


def log_path() -> Path:
    """Return the absolute path to the history log."""
    return config_dir() / LOG_FILENAME


def _timestamp() -> str:
    """Return an ISO-8601 timestamp with timezone offset."""
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def log_event(event: str, command: str, *, note: str = "") -> bool:
    """Append a single event to the history log.

    Returns ``True`` on success, ``False`` if the write failed. Newlines in the
    command are collapsed so each log entry stays on one line and the file
    remains trivially greppable.
    """
    command = " ".join(command.split())  # Flatten any embedded newlines.
    line = f"{_timestamp()}\t{event:<7}\t{command}"
    if note:
        note = " ".join(note.split())
        line += f"\t# {note}"
    try:
        ensure_config_dir()
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except OSError:
        return False


def log_command(command: str, *, dry_run: bool = False, note: str = "") -> bool:
    """Convenience wrapper: log a command as EXEC or DRYRUN."""
    return log_event(EVENT_DRYRUN if dry_run else EVENT_EXEC, command, note=note)


def read_history(limit: Optional[int] = None) -> list[str]:
    """Return history log lines (most recent last).

    ``limit`` caps the number of returned lines (the tail). Returns an empty
    list if the log does not exist yet.
    """
    try:
        with open(log_path(), "r", encoding="utf-8") as fh:
            lines = [ln.rstrip("\n") for ln in fh]
    except OSError:
        return []
    if limit is not None and limit >= 0:
        return lines[-limit:]
    return lines
