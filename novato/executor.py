# SPDX-License-Identifier: GPL-3.0-or-later
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
import time
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
    elapsed_seconds: float = 0.0

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

    try:
        exit_code = _stream(run_cmd, on_line or _print_line)
    except KeyboardInterrupt:
        # The user pressed Ctrl+C: the child got the same SIGINT and is
        # winding down. 130 = 128 + SIGINT, the shell convention.
        return ExecResult(run_cmd, 130, executed=True, reason="cancelled by user")
    except FileNotFoundError as exc:
        return ExecResult(run_cmd, 127, executed=True, reason=str(exc))
    except OSError as exc:
        return ExecResult(run_cmd, 1, executed=True, reason=str(exc))
    return ExecResult(run_cmd, exit_code, executed=True)


def execute_argv(
    argv: list[str] | tuple[str, ...],
    *,
    dry_run: bool = False,
    event: str = _logger.EVENT_EXEC,
    note: str = "agent action",
    on_progress: Optional[Callable[[float], None]] = None,
) -> ExecResult:
    """Execute an already policy-approved argument vector without a shell.

    Agent actions use this entry point so pipes, redirects, substitutions, and
    quoting tricks are data rather than shell syntax. The string safety layer
    is still applied defensively before execution.
    """
    args = [str(arg) for arg in argv]
    if not args or any("\x00" in arg or "\n" in arg for arg in args):
        return ExecResult("", 1, executed=False, blocked=True,
                          reason="invalid argument vector")
    # Import lazily to avoid making the normal executor depend on the agent at
    # module import time. Agent argv must pass both the narrow allowlist and the
    # general destructive-command validator.
    from .agent_tools import validate_action_argv

    approved, policy_reason = validate_action_argv(args)
    if not approved:
        return ExecResult(shlex.join(args), 1, executed=False, blocked=True,
                          reason=policy_reason)
    command = shlex.join(args)
    verdict = _safety.validate(command)
    if not verdict.allowed:
        return ExecResult(command, 1, executed=False, blocked=True,
                          reason=verdict.reason)
    # The agent policy rejects auto-confirm flags rather than silently changing
    # an approved proposal after it was shown to the user.
    if verdict.sanitized and verdict.sanitized != command:
        return ExecResult(command, 1, executed=False, blocked=True,
                          reason="auto-confirm flags are not allowed in agent actions")
    if dry_run:
        _logger.log_command(command, dry_run=True, note=note)
        return ExecResult(command, 0, executed=False, dry_run=True,
                          reason="dry-run: not executed")
    _logger.log_event(event, command, note=note)
    started = time.monotonic()
    proc = None
    try:
        proc = subprocess.Popen(args)
        next_update = 30.0
        while True:
            try:
                code = proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                if on_progress is not None and elapsed >= next_update:
                    on_progress(elapsed)
                    next_update += 30.0
    except KeyboardInterrupt:
        if proc is not None:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        return ExecResult(command, 130, executed=True, reason="cancelled by user",
                          elapsed_seconds=time.monotonic() - started)
    except FileNotFoundError as exc:
        return ExecResult(command, 127, executed=True, reason=str(exc),
                          elapsed_seconds=time.monotonic() - started)
    except OSError as exc:
        return ExecResult(command, 1, executed=True, reason=str(exc),
                          elapsed_seconds=time.monotonic() - started)
    return ExecResult(command, code, executed=True,
                      elapsed_seconds=time.monotonic() - started)


def _print_line(line: str) -> None:
    print(line)


def _stream(command: str, sink: Callable[[str], None]) -> int:
    """Run ``command`` with the terminal's own stdin/stdout/stderr inherited.

    Inheriting the TTY lets interactive programs (pacman, apt, dnf) display
    their own prompts and read user input directly — no hidden [Y/n] prompts.
    The ``sink`` callback is kept for API compatibility but output goes
    straight to the terminal rather than through the callback.
    """
    tokens = shlex.split(command)
    proc = subprocess.run(tokens)
    return proc.returncode
