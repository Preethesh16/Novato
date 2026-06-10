"""Command execution with live output streaming.

The executor is the *only* place in Novato that runs a state-changing command,
and it does so under three hard rules:

* It must be handed a command that already passed :func:`novato.safety.validate`
  (``Risk`` is not ``BLOCKED``) and explicit user confirmation. The executor
  re-validates defensively as a second gate.
* In ``--dry-run`` it never executes — it prints and logs a ``DRYRUN`` entry.
* Every executed command is logged to ``~/.novato/history.log`` (safety rule #6)
  *before* it runs, so even a crashing install leaves an audit trail.

Output is streamed line-by-line to the user's terminal so a long ``pacman``
download feels live rather than frozen.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

from . import logger as _logger
from . import safety as _safety


@dataclass
class ExecResult:
    """Outcome of an execution attempt."""

    command: str
    exit_code: int
    executed: bool          # False for dry-run or blocked/declined.
    dry_run: bool = False
    blocked: bool = False
    reason: str = ""

    @property
    def succeeded(self) -> bool:
        return self.executed and self.exit_code == 0


def execute(
    command: str,
    *,
    dry_run: bool = False,
    event: str = _logger.EVENT_EXEC,
    on_line: Optional[Callable[[str], None]] = None,
    note: str = "",
) -> ExecResult:
    """Run ``command``, streaming output, after a defensive safety re-check.

    Parameters
    ----------
    dry_run:
        When True, the command is logged as ``DRYRUN`` and *not* executed.
    event:
        Log event kind (``EXEC`` or ``FIX``).
    on_line:
        Optional callback invoked with each stdout line (already stripped of the
        trailing newline). Defaults to printing to stdout.
    """
    command = command.strip()
    verdict = _safety.validate(command)
    if not verdict.allowed:
        return ExecResult(command, 1, executed=False, blocked=True,
                          reason=verdict.reason)

    # Always operate on the sanitised form (auto-confirm flags removed).
    run_cmd = verdict.sanitized or command

    if dry_run:
        _logger.log_command(run_cmd, dry_run=True, note=note or "dry-run")
        return ExecResult(run_cmd, 0, executed=False, dry_run=True,
                          reason="dry-run: not executed")

    # Log BEFORE executing so a crash still leaves an audit trail.
    _logger.log_event(event, run_cmd, note=note)

    sink = on_line if on_line is not None else _print_line
    try:
        exit_code = _stream(run_cmd, sink)
    except FileNotFoundError as exc:
        return ExecResult(run_cmd, 127, executed=True, reason=str(exc))
    except OSError as exc:
        return ExecResult(run_cmd, 1, executed=True, reason=str(exc))
    return ExecResult(run_cmd, exit_code, executed=True)


def _print_line(line: str) -> None:
    print(line)


def _stream(command: str, sink: Callable[[str], None]) -> int:
    """Run ``command`` and feed each combined stdout/stderr line to ``sink``.

    Uses the user's shell semantics minimally: we tokenise with ``shlex`` and run
    without ``shell=True`` so there is no extra shell-injection surface. Commands
    that genuinely need a shell pipeline are out of scope for installs.
    """
    tokens = shlex.split(command)
    proc = subprocess.Popen(
        tokens,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sink(line.rstrip("\n"))
    proc.stdout.close()
    return proc.wait()
