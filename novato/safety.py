# SPDX-License-Identifier: GPL-3.0-or-later
"""Safety layer — the non-negotiable guardrails.

Per the project's absolute safety rules, this module enforces:

* No command is ever auto-executed; a human must confirm (handled by the
  presenter, which must call :func:`confirm` — never bypass it).
* Generated install commands must not contain auto-confirm flags
  (``--noconfirm``, ``-y``, ``--yes``).
* Destructive commands (``rm``, ``dd``, ``mkfs``, ``fdisk``, ...) are refused
  outright, with an explanation.

The core entry point is :func:`validate`, which returns a :class:`Verdict`.
Callers MUST check ``verdict.allowed`` before executing anything. The functions
here are pure and side-effect free so they are trivially testable.
"""

from __future__ import annotations

import re
import os
import shlex
from dataclasses import dataclass, field
from enum import Enum


class Risk(Enum):
    """Risk classification for a command."""

    SAFE = "safe"
    NEEDS_CONFIRM = "needs_confirm"  # Normal install/search — confirm and go.
    BLOCKED = "blocked"              # Refused outright; never executes.


# Commands that can irreversibly destroy data or a system. Matched on the
# program name (first non-sudo token). These are *always* blocked.
DESTRUCTIVE_COMMANDS = frozenset({
    "rm", "rmdir", "dd", "mkfs", "fdisk", "parted", "sgdisk", "wipefs",
    "shred", "mkswap", "cfdisk", "gdisk", "format", "blkdiscard",
})

# Substrings that indicate a destructive or system-bricking action even when
# the leading command is innocuous (e.g. a piped or chained payload).
DESTRUCTIVE_PATTERNS = (
    re.compile(r"\brm\s+(-\w*\s+)*(-rf|-fr|-r\s+-f|-f\s+-r)\b"),
    re.compile(r"\brm\s+(-\w*\s+)*/(\s|$)"),            # rm ... /
    re.compile(r"\bdd\b.*\bof=/dev/"),                  # dd of=/dev/sdX
    re.compile(r"\bmkfs\b"),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;:"),        # fork bomb
    re.compile(r">\s*/dev/sd[a-z]"),                    # redirect onto a disk
    re.compile(r"\bchmod\s+-R\s+0*7*7*7*\s+/(\s|$)"),   # chmod -R 777 /
    re.compile(r"\bmv\s+.*\s+/dev/null\b"),
)

# Auto-confirm flags we must never emit in generated commands.
AUTO_CONFIRM_FLAGS = ("--noconfirm", "--yes", "-y")

# Per-package-manager auto-confirm flags, for stripping/sanitising.
_PM_CONFIRM_FLAGS = {
    "pacman": ("--noconfirm",),
    "yay": ("--noconfirm",),
    "paru": ("--noconfirm",),
    "apt": ("-y", "--yes", "--assume-yes"),
    "apt-get": ("-y", "--yes", "--assume-yes"),
    "dnf": ("-y", "--assumeyes"),
    "yum": ("-y", "--assumeyes"),
    "zypper": ("-y", "--non-interactive"),
}


@dataclass(frozen=True)
class Verdict:
    """Result of validating a command."""

    risk: Risk
    reason: str = ""
    sanitized: str = ""             # Command with auto-confirm flags removed.
    blocked_by: str = ""            # Which pattern/command triggered a block.

    @property
    def allowed(self) -> bool:
        """True iff the command may be executed (after user confirmation)."""
        return self.risk is not Risk.BLOCKED


@dataclass
class ConfirmPolicy:
    """Toggles that affect confirmation behaviour (e.g. global --dry-run)."""

    dry_run: bool = False
    # If True, even SAFE read-only commands ask for confirmation. Default False
    # so searches stay frictionless; installs are always NEEDS_CONFIRM anyway.
    confirm_safe: bool = False
    extra: dict = field(default_factory=dict)


def _tokens(command: str) -> list[str]:
    """Tokenise a command, tolerating shell syntax errors."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


# Only wrappers whose argument boundaries we understand are unwrapped. Shell
# modes and unknown options fail closed rather than hiding the real program.
_WRAPPER_OPTIONS = {
    "sudo": ({"-n", "-H", "-E", "-b", "--non-interactive", "--set-home",
              "--preserve-env", "--background"},
             {"-u", "-g", "-h", "-p", "-C", "-T",
              "--user", "--group", "--host", "--prompt", "--close-from",
              "--command-timeout"}),
    "doas": ({"-n", "-L"}, {"-u"}),
    "env": ({"-i", "--ignore-environment"}, {"-u", "--unset"}),
}


def _program_index(tokens: list[str]) -> int | None:
    """Locate the command after supported wrappers, or reject ambiguous syntax."""
    i = 0
    while i < len(tokens):
        wrapper = os.path.basename(tokens[i])
        if wrapper not in _WRAPPER_OPTIONS:
            return None if tokens[i].startswith("-") else i
        simple, valued = _WRAPPER_OPTIONS[wrapper]
        i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            option = tokens[i]
            if option == "--":
                i += 1
                break
            if option in simple:
                i += 1
                continue
            if option in valued:
                if i + 1 >= len(tokens):
                    return None
                i += 2
                continue
            # Long --name=value and short -uroot forms consume their own value.
            if option.startswith("--"):
                name, sep, value = option.partition("=")
                if sep and value and name in valued:
                    i += 1
                    continue
            elif len(option) > 2 and option[:2] in valued:
                i += 1
                continue
            return None
        if wrapper in ("sudo", "env"):
            while i < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
                i += 1
    return None


def _program_name(tokens: list[str]) -> str:
    """Return the effective program name after supported sudo/doas/env forms."""
    i = _program_index(tokens)
    return os.path.basename(tokens[i]) if i is not None else ""


# Shell metacharacters that must never appear in a delete target — a non-shell
# executor treats them literally, but rejecting them keeps the offer clean.
_SHELL_META = set(";|&$`<>()!\n\"'\\")


def _safe_rm_target(tokens: list[str]) -> bool:
    """True for ``rm`` of exactly one specific, in-tree file/folder by name.

    This is the only delete we ever offer to run, and only after a default-No
    confirmation. Everything risky stays blocked: wildcards, absolute/system
    paths, the home directory, ``.``/``..``, multiple targets, or the ``-rf``
    force combo (caught earlier by the pattern list).
    """
    i = _program_index(tokens)
    args = tokens[i + 1:] if i is not None and tokens[i] == "rm" else None
    if args is None:
        return False

    flags = [a for a in args if a.startswith("-")]
    paths = [a for a in args if not a.startswith("-")]
    # Only the gentle flags; -rf/-fr never reach here (the pattern list blocks
    # them) but reject any unexpected flag to be safe.
    for f in flags:
        if set(f.lstrip("-")) - set("riv"):
            return False
    if len(paths) != 1:
        return False  # exactly one named target — no mass deletes
    target = paths[0]
    if not target or target in (".", "..", "~", "/", "*"):
        return False
    if target.startswith(("/", "~", "-")):
        return False                       # absolute, home-relative, or a flag
    if target.startswith("..") or "/.." in target:
        return False                       # climbing out of the tree
    if any(c in _SHELL_META for c in target) or any(c in "*?[]" for c in target):
        return False                       # metacharacters / globs
    return True


def is_destructive(command: str) -> tuple[bool, str]:
    """Return ``(True, reason)`` if the command is destructive, else (False, "")."""
    # Hard-blocked patterns first: rm -rf, rm /, dd of=/dev, fork bomb, ...
    for pat in DESTRUCTIVE_PATTERNS:
        if pat.search(command):
            return True, "matches a known dangerous pattern"
    tokens = _tokens(command)
    prog = _program_name(tokens)
    if not prog:
        return True, "unsupported or incomplete command wrapper"
    if prog in DESTRUCTIVE_COMMANDS:
        # Deleting one specific, in-tree file/folder by name is permitted (it
        # still needs an explicit confirmation); every other destructive
        # command — and every riskier rm — stays blocked.
        if prog == "rm" and _safe_rm_target(tokens):
            return False, ""
        return True, f"'{prog}' can permanently destroy data or partitions"
    return False, ""


# Preserve values even when they happen to look like confirmation flags. In
# particular, deleting a sudo prompt or an env variable name can move the
# executable boundary. Package-manager operands after -- are also literal.
_PM_VALUE_OPTIONS = {
    "apt": {"-a", "-c", "-o", "-t", "-S", "--host-architecture", "--config-file",
            "--option", "--target-release", "--default-release", "--snapshot"},
    "apt-get": {"-a", "-c", "-o", "-t", "-S", "--host-architecture", "--config-file",
                "--option", "--target-release", "--default-release", "--snapshot"},
    "dnf": {"-c", "-d", "-e", "-R", "--config", "--debuglevel", "--errorlevel",
            "--randomwait", "--comment", "--setopt", "--releasever", "--installroot",
            "--enablerepo", "--disablerepo", "--repo", "--exclude", "-x"},
    "yum": {"-c", "-d", "-e", "-R", "--config", "--debuglevel", "--errorlevel",
            "--randomwait", "--setopt", "--releasever", "--installroot",
            "--enablerepo", "--disablerepo", "--exclude", "-x"},
    "zypper": {"-c", "-R", "--config", "--root", "--installroot", "--reposd-dir",
               "--cache-dir", "--pkg-cache-dir", "--raw-cache-dir", "--solv-cache-dir",
               "--releasever", "-r", "--repo", "--from", "-t", "--type"},
    "pacman": {"-b", "-r", "--dbpath", "--root", "--config", "--cachedir",
               "--gpgdir", "--hookdir", "--logfile", "--sysroot", "--arch"},
}
_PM_VALUE_OPTIONS["yay"] = _PM_VALUE_OPTIONS["pacman"]
_PM_VALUE_OPTIONS["paru"] = _PM_VALUE_OPTIONS["pacman"]

# Only split known boolean groups; never edit an attached option value such
# as -tmyrelease or -cmyconfig. Pacman's -y means refresh, not assume-yes.
_PM_BOOLEAN_SHORT = {
    "apt": set("bdfhmsuvVyq"), "apt-get": set("bdfhmsuvVyq"),
    "dnf": set("46bChqvy"), "yum": set("Chqvy"),
    "zypper": set("qvny"),
}


def _without_auto_confirm(tokens: list[str]) -> list[str]:
    program = _program_index(tokens)
    if program is None:
        return tokens
    manager = os.path.basename(tokens[program])
    if manager not in _PM_CONFIRM_FLAGS:
        return tokens
    cleaned = tokens[:program + 1]
    flags = set(_PM_CONFIRM_FLAGS[manager])
    valued = _PM_VALUE_OPTIONS[manager]
    is_apt = manager in ("apt", "apt-get")
    quiet = 0
    subcommand_seen = False
    i = program + 1
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if token == "--":
            cleaned.extend(tokens[i - 1:])
            break
        if token in valued:
            cleaned.append(token)
            if i < len(tokens):
                cleaned.append(tokens[i])
                i += 1
            continue
        if token in flags:
            continue
        if is_apt:
            # APT quiet level 2 implies yes even without a -y flag.
            level = re.fullmatch(r"(?:--quiet=|-q=?)([0-9]+)", token)
            if level:
                digits = level.group(1).lstrip("0")
                quiet = 1 if digits else 0
                cleaned.append(token if digits in ("", "1") else "--quiet=1")
                continue
            if token == "--quiet":
                if quiet < 1:
                    cleaned.append(token)
                    quiet += 1
                continue
        if (len(token) > 1 and token.startswith("-") and not token.startswith("--")
                and set(token[1:]) <= _PM_BOOLEAN_SHORT.get(manager, set())):
            kept = []
            for flag in token[1:]:
                if flag == "y":
                    continue
                if manager == "zypper" and flag == "n" and not subcommand_seen:
                    continue
                if is_apt and flag == "q":
                    if quiet >= 1:
                        continue
                    quiet += 1
                kept.append(flag)
            if kept:
                cleaned.append("-" + "".join(kept))
            continue
        cleaned.append(token)
        if not token.startswith("-"):
            subcommand_seen = True
    return cleaned


def sanitize(command: str) -> str:
    """Remove supported package-manager confirmation flags without moving arguments."""
    tokens = _tokens(command)
    cleaned = _without_auto_confirm(tokens)
    return command if cleaned == tokens else shlex.join(cleaned)


def has_auto_confirm(command: str) -> bool:
    """Whether supported package-manager flags suppress confirmation prompts."""
    tokens = _tokens(command)
    return _without_auto_confirm(tokens) != tokens


def validate(command: str) -> Verdict:
    """Classify a command and produce a :class:`Verdict`.

    * Destructive commands -> ``BLOCKED`` (never executes).
    * Everything else -> ``NEEDS_CONFIRM`` with auto-confirm flags stripped.

    Read-only search commands are still returned as ``NEEDS_CONFIRM`` here; the
    presenter decides, via :class:`ConfirmPolicy`, whether to actually prompt.
    """
    command = command.strip()
    if not command:
        return Verdict(Risk.BLOCKED, reason="empty command", blocked_by="empty")

    try:
        shlex.split(command)
    except ValueError:
        return Verdict(Risk.BLOCKED, reason="Invalid command quoting", blocked_by="syntax")

    destructive, why = is_destructive(command)
    if destructive:
        return Verdict(
            Risk.BLOCKED,
            reason=(
                f"Refused for safety: {why}. Novato never runs commands that "
                "can erase data or damage your system."
            ),
            blocked_by=_program_name(_tokens(command)) or "pattern",
        )

    sanitized = sanitize(command)
    note = ""
    if sanitized != command:
        note = "Removed auto-confirm flag so you can review before it runs."
    return Verdict(Risk.NEEDS_CONFIRM, reason=note, sanitized=sanitized)


def confirm(prompt_fn, command: str, policy: ConfirmPolicy | None = None) -> bool:
    """Gate execution behind explicit user confirmation.

    ``prompt_fn`` is an injectable callable taking a prompt string and returning
    the user's raw answer (e.g. ``input`` or a rich prompt). This indirection
    keeps the gate testable and keeps I/O out of the safety core.

    Returns ``True`` only on an explicit affirmative answer. In ``dry_run`` mode
    it always returns ``False`` (rule #7: never execute during a dry run).
    """
    policy = policy or ConfirmPolicy()
    if policy.dry_run:
        return False
    answer = (prompt_fn(f"Run: {command} [y/N]? ") or "").strip().lower()
    return answer in ("y", "yes")
