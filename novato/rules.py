"""Hardcoded error-correction rules for the /mistake watcher (Basic mode).

Each rule inspects an :class:`ErrorContext` (the failed command, its exit code,
captured stderr, and the detected system) and may return a :class:`Correction`
describing what went wrong, *why*, and a suggested fix. Rules are tried in
order; the first match wins. This module is pure and dependency-free so it can
run instantly and be exhaustively unit-tested.

Adding a rule
-------------
Append a function decorated with ``@rule`` that returns a ``Correction`` on
match or ``None`` otherwise. Keep explanations beginner-friendly: assume the
reader has never used Linux before. Never suggest a destructive command — the
safety layer will reject it anyway, but rules should not even propose one.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Callable, Optional

# Known package-manager front-ends, used to detect "wrong PM for this distro".
_PM_TO_FAMILY = {
    "apt": "Ubuntu/Debian",
    "apt-get": "Ubuntu/Debian",
    "dpkg": "Ubuntu/Debian",
    "pacman": "Arch",
    "yay": "Arch (AUR)",
    "paru": "Arch (AUR)",
    "dnf": "Fedora/RHEL",
    "yum": "Fedora/RHEL (old)",
    "zypper": "openSUSE",
    "emerge": "Gentoo",
    "apk": "Alpine",
}

# Common command typos -> correct command. Extend freely.
_COMMON_COMMANDS = [
    "pacman", "yay", "paru", "apt", "apt-get", "dnf", "zypper", "sudo",
    "systemctl", "journalctl", "git", "python", "python3", "pip", "pip3",
    "docker", "ls", "cd", "grep", "find", "make", "cmake", "ssh", "scp",
    "cat", "nano", "vim", "nvim", "mkdir", "rmdir", "chmod", "chown",
    "curl", "wget", "tar", "unzip", "mount", "umount", "ping", "ip",
]


@dataclass(frozen=True)
class ErrorContext:
    """Everything a rule needs to reason about a failed command."""

    command: str
    exit_code: int
    stderr: str = ""
    distro_id: str = ""
    package_manager: str = ""  # The PM correct for *this* system.
    install_cmd: str = ""      # e.g. "sudo pacman -S".

    @property
    def first_word(self) -> str:
        parts = self.command.split()
        return parts[0] if parts else ""

    @property
    def words(self) -> list[str]:
        return self.command.split()


@dataclass(frozen=True)
class Correction:
    """A beginner-friendly diagnosis plus an optional runnable fix."""

    title: str        # Short error summary, e.g. "'pacmna' command not found".
    reason: str       # Plain-English explanation of *why* it failed.
    fix: str = ""     # Suggested command to run (empty if none).
    confidence: float = 0.8  # 0..1; used to decide whether to surface it.
    rule_name: str = ""


# Registry of rule callables, in priority order.
_RULES: list[Callable[[ErrorContext], Optional[Correction]]] = []


def rule(func: Callable[[ErrorContext], Optional[Correction]]):
    """Decorator that registers ``func`` as an error-correction rule."""
    _RULES.append(func)
    return func


def _strip_sudo(words: list[str]) -> tuple[bool, list[str]]:
    """Return ``(had_sudo, words_without_sudo)``."""
    if words and words[0] == "sudo":
        return True, words[1:]
    return False, words


# ---------------------------------------------------------------------------
# Rules. Order = priority.
# ---------------------------------------------------------------------------

@rule
def wrong_package_manager(ctx: ErrorContext) -> Optional[Correction]:
    """User invoked a package manager that belongs to a different distro."""
    _, words = _strip_sudo(ctx.words)
    if not words:
        return None
    cmd = words[0]
    if cmd not in _PM_TO_FAMILY:
        return None
    # Only fire when that PM is *not* this system's PM and it's missing.
    if ctx.package_manager and cmd == ctx.package_manager:
        return None
    if "not found" not in ctx.stderr.lower() and ctx.exit_code not in (127,):
        # If it ran, it's probably the right PM; don't second-guess.
        if ctx.package_manager and cmd != ctx.package_manager:
            pass
        else:
            return None

    family = _PM_TO_FAMILY[cmd]
    fix = ""
    if ctx.install_cmd and len(words) > 1:
        # Re-map the package args onto the correct install command.
        pkg_args = _extract_packages(words)
        if pkg_args:
            fix = f"{ctx.install_cmd} {' '.join(pkg_args)}"
    this = ctx.distro_id.title() or "this system"
    return Correction(
        title=f"'{cmd}' is not the package manager for {this}",
        reason=(
            f"'{cmd}' is {family}'s package manager. "
            f"You're on {this}, which uses '{ctx.package_manager or 'a different tool'}'."
        ),
        fix=fix,
        confidence=0.92,
        rule_name="wrong_package_manager",
    )


# Package-manager subcommands that are not package names.
_PM_SUBCOMMANDS = frozenset({
    "install", "remove", "search", "update", "upgrade", "reinstall",
    "in", "rm", "se", "ref", "refresh", "info", "show", "list",
})


def _extract_packages(words: list[str]) -> list[str]:
    """Best-effort: pull package names out of a PM invocation.

    Skips flags (``-S``, ``--needed``) and verb subcommands (``install``,
    ``search``, …) so ``apt install vlc`` yields just ``["vlc"]``.
    """
    pkgs = []
    for w in words[1:]:
        if w.startswith("-"):
            continue
        if w.lower() in _PM_SUBCOMMANDS:
            continue
        pkgs.append(w)
    return pkgs


@rule
def command_typo(ctx: ErrorContext) -> Optional[Correction]:
    """A single mistyped command (e.g. 'pacmna' -> 'pacman')."""
    if "not found" not in ctx.stderr.lower() and ctx.exit_code != 127:
        return None
    had_sudo, words = _strip_sudo(ctx.words)
    if not words:
        return None
    cmd = words[0]
    if cmd in _COMMON_COMMANDS:
        return None  # Spelled correctly; a different rule applies.
    matches = difflib.get_close_matches(cmd, _COMMON_COMMANDS, n=1, cutoff=0.7)
    if not matches:
        return None
    suggestion = matches[0]
    fixed_words = (["sudo"] if had_sudo else []) + [suggestion] + words[1:]
    return Correction(
        title=f"'{cmd}' command not found",
        reason=f"Looks like a typo — did you mean '{suggestion}'?",
        fix=" ".join(fixed_words),
        confidence=0.85,
        rule_name="command_typo",
    )


@rule
def missing_sudo(ctx: ErrorContext) -> Optional[Correction]:
    """Operation needs root but was run without sudo."""
    text = ctx.stderr.lower()
    needs_root = any(
        p in text
        for p in (
            "you cannot perform this operation unless you are root",
            "permission denied",
            "are you root",
            "must be run as root",
            "operation not permitted",
            "eacces",
        )
    )
    if not needs_root:
        return None
    if ctx.first_word == "sudo":
        return None  # Already elevated; root-cause is elsewhere.
    return Correction(
        title="Permission denied — needs administrator (root) access",
        reason=(
            "This command changes system files, which requires admin rights. "
            "Add 'sudo' to run it as the administrator."
        ),
        fix=f"sudo {ctx.command}",
        confidence=0.88,
        rule_name="missing_sudo",
    )


@rule
def python_module_missing(ctx: ErrorContext) -> Optional[Correction]:
    """ModuleNotFoundError / ImportError for a missing pip package."""
    m = re.search(r"No module named ['\"]([\w.]+)['\"]", ctx.stderr)
    if not m:
        return None
    module = m.group(1).split(".")[0]
    return Correction(
        title=f"Python module '{module}' is not installed",
        reason=(
            f"The script needs the '{module}' library, but it isn't installed "
            "in your Python environment yet."
        ),
        fix=f"pip install {module}",
        confidence=0.8,
        rule_name="python_module_missing",
    )


@rule
def command_not_found_install_hint(ctx: ErrorContext) -> Optional[Correction]:
    """A real program isn't installed — hint how to install it."""
    if "not found" not in ctx.stderr.lower() and ctx.exit_code != 127:
        return None
    had_sudo, words = _strip_sudo(ctx.words)
    if not words:
        return None
    cmd = words[0]
    # Only when it's NOT a typo of a known command and NOT a PM.
    if cmd in _PM_TO_FAMILY:
        return None
    if difflib.get_close_matches(cmd, _COMMON_COMMANDS, n=1, cutoff=0.7):
        return None
    if not ctx.install_cmd:
        return None
    return Correction(
        title=f"'{cmd}' is not installed",
        reason=(
            f"The program '{cmd}' isn't on your system yet. If you know the "
            "package name, install it; or ask Novato to find it for you."
        ),
        fix=f"{ctx.install_cmd} {cmd}",
        confidence=0.55,
        rule_name="command_not_found_install_hint",
    )


@rule
def file_not_found(ctx: ErrorContext) -> Optional[Correction]:
    """A referenced file or directory does not exist."""
    text = ctx.stderr.lower()
    if "no such file or directory" not in text:
        return None
    return Correction(
        title="File or directory not found",
        reason=(
            "The path you referenced doesn't exist. Check for typos, and use "
            "'ls' to see what's actually in the current folder."
        ),
        fix="",
        confidence=0.6,
        rule_name="file_not_found",
    )


@rule
def pacman_db_lock(ctx: ErrorContext) -> Optional[Correction]:
    """pacman database is locked by a stale lockfile."""
    if "unable to lock database" not in ctx.stderr.lower():
        return None
    return Correction(
        title="pacman database is locked",
        reason=(
            "Another package operation is running, or a previous one crashed "
            "and left a lock file behind. If nothing else is installing, the "
            "lock can be safely removed."
        ),
        fix="sudo rm /var/lib/pacman/db.lck",
        confidence=0.7,
        rule_name="pacman_db_lock",
    )


@rule
def apt_needs_update(ctx: ErrorContext) -> Optional[Correction]:
    """apt package list is stale -> 'Unable to locate package'."""
    if "unable to locate package" not in ctx.stderr.lower():
        return None
    return Correction(
        title="Package not found in apt's local list",
        reason=(
            "Your package list may be out of date, or the package name is "
            "spelled differently. Refresh the list first, then try again."
        ),
        fix="sudo apt update",
        confidence=0.65,
        rule_name="apt_needs_update",
    )


@rule
def git_not_a_repo(ctx: ErrorContext) -> Optional[Correction]:
    """Ran a git command outside a repository."""
    if "not a git repository" not in ctx.stderr.lower():
        return None
    return Correction(
        title="This folder isn't a Git repository",
        reason=(
            "Git commands only work inside a repository. Either 'cd' into your "
            "project, or run 'git init' to start tracking this folder."
        ),
        fix="git init",
        confidence=0.6,
        rule_name="git_not_a_repo",
    )


@rule
def disk_full(ctx: ErrorContext) -> Optional[Correction]:
    """Out of disk space."""
    if "no space left on device" not in ctx.stderr.lower():
        return None
    return Correction(
        title="Your disk is full",
        reason=(
            "There's no free space left on the drive. Free some up before "
            "retrying — check what's using space with a disk analyser."
        ),
        fix="df -h",
        confidence=0.75,
        rule_name="disk_full",
    )


@rule
def address_in_use(ctx: ErrorContext) -> Optional[Correction]:
    """A network port is already taken."""
    text = ctx.stderr.lower()
    if "address already in use" not in text and "port is already" not in text:
        return None
    return Correction(
        title="That network port is already in use",
        reason=(
            "Another program is already listening on this port. Find and stop "
            "it, or run your program on a different port."
        ),
        fix="ss -tulpn",
        confidence=0.7,
        rule_name="address_in_use",
    )


@rule
def command_not_found_handler_hint(ctx: ErrorContext) -> Optional[Correction]:
    """Generic 'command not found' with no better match — gentle guidance."""
    text = ctx.stderr.lower()
    if "command not found" not in text and ctx.exit_code != 127:
        return None
    _, words = _strip_sudo(ctx.words)
    if not words:
        return None
    cmd = words[0]
    if cmd in _PM_TO_FAMILY or cmd in _COMMON_COMMANDS:
        return None
    if difflib.get_close_matches(cmd, _COMMON_COMMANDS, n=1, cutoff=0.7):
        return None
    if ctx.install_cmd:  # A stronger install hint already covers this case.
        return None
    return Correction(
        title=f"'{cmd}' isn't a known command",
        reason=(
            "It may be misspelled, or the program providing it isn't installed. "
            "Try describing what you want with: novato \"...\"."
        ),
        confidence=0.5,
        rule_name="command_not_found_handler_hint",
    )


@rule
def connection_refused(ctx: ErrorContext) -> Optional[Correction]:
    """Network connection refused / unreachable."""
    text = ctx.stderr.lower()
    if not any(p in text for p in ("connection refused", "could not resolve host",
                                   "network is unreachable", "temporary failure in name")):
        return None
    return Correction(
        title="Couldn't reach the network",
        reason=(
            "The connection failed — you may be offline, the server may be down, "
            "or DNS isn't resolving. Check your internet connection first."
        ),
        fix="ping -c 3 archlinux.org",
        confidence=0.6,
        rule_name="connection_refused",
    )


@rule
def pacman_key_error(ctx: ErrorContext) -> Optional[Correction]:
    """pacman signature / keyring problems."""
    text = ctx.stderr.lower()
    if not any(p in text for p in ("signature is unknown trust",
                                   "invalid or corrupted package",
                                   "key.*could not be looked up",
                                   "marginal trust")):
        if "signature" not in text or "pacman" not in ctx.command:
            return None
    return Correction(
        title="pacman package signature problem",
        reason=(
            "Your keyring is out of date, so pacman can't verify packages. "
            "Refreshing the Arch keyring usually fixes this."
        ),
        fix="sudo pacman -S archlinux-keyring",
        confidence=0.6,
        rule_name="pacman_key_error",
    )


@rule
def npm_module_missing(ctx: ErrorContext) -> Optional[Correction]:
    """Node 'Cannot find module' error."""
    m = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", ctx.stderr)
    if not m:
        return None
    module = m.group(1)
    if module.startswith(".") or module.startswith("/"):
        return None  # A local path, not an npm package.
    pkg = module.split("/")[0] if not module.startswith("@") else "/".join(module.split("/")[:2])
    return Correction(
        title=f"Node module '{pkg}' is not installed",
        reason="This project needs a package that isn't installed yet.",
        fix=f"npm install {pkg}",
        confidence=0.7,
        rule_name="npm_module_missing",
    )


@rule
def make_command_missing(ctx: ErrorContext) -> Optional[Correction]:
    """Building from source but base build tools are missing."""
    text = ctx.stderr.lower()
    if "make: command not found" not in text and "gcc: command not found" not in text:
        return None
    fix = f"{ctx.install_cmd} base-devel" if ctx.package_manager == "pacman" else (
        f"{ctx.install_cmd} build-essential" if ctx.install_cmd else ""
    )
    return Correction(
        title="Build tools are not installed",
        reason=(
            "Compiling software needs a compiler and 'make'. Install your "
            "distro's base development tools first."
        ),
        fix=fix,
        confidence=0.7,
        rule_name="make_command_missing",
    )


@rule
def permission_denied_script(ctx: ErrorContext) -> Optional[Correction]:
    """Tried to run a script without the executable bit set."""
    text = ctx.stderr.lower()
    if "permission denied" not in text:
        return None
    # Heuristic: running a local file like ./script.sh or ./run.
    first = ctx.first_word
    if not (first.startswith("./") or first.startswith("/") or first.startswith("../")):
        return None
    return Correction(
        title="That file isn't marked as executable",
        reason=(
            "The script exists but doesn't have permission to run. Mark it "
            "executable with chmod, then run it again."
        ),
        fix=f"chmod +x {first}",
        confidence=0.6,
        rule_name="permission_denied_script",
    )


@rule
def cd_into_file(ctx: ErrorContext) -> Optional[Correction]:
    """'cd' into something that isn't a directory."""
    text = ctx.stderr.lower()
    if "not a directory" not in text or ctx.first_word != "cd":
        return None
    return Correction(
        title="That's a file, not a folder",
        reason="'cd' only moves into directories. Use 'ls' to see what's there.",
        confidence=0.6,
        rule_name="cd_into_file",
    )


@rule
def dnf_no_match(ctx: ErrorContext) -> Optional[Correction]:
    """dnf couldn't find a package."""
    text = ctx.stderr.lower()
    if "no match for argument" not in text and "unable to find a match" not in text:
        return None
    return Correction(
        title="dnf couldn't find that package",
        reason=(
            "The package name may differ on Fedora, or you may need an extra "
            "repository (like RPM Fusion). Try searching for it first."
        ),
        fix="dnf search " + (ctx.words[-1] if ctx.words else ""),
        confidence=0.55,
        rule_name="dnf_no_match",
    )


def analyze(ctx: ErrorContext, *, min_confidence: float = 0.5) -> Optional[Correction]:
    """Run all rules in order and return the first confident match.

    Returns ``None`` when no rule matches or the best match is below
    ``min_confidence`` — in which case the caller may escalate to an AI backend.
    """
    if ctx.exit_code == 0:
        return None
    for fn in _RULES:
        try:
            result = fn(ctx)
        except Exception:
            # A buggy rule must never crash the user's shell.
            continue
        if result and result.confidence >= min_confidence:
            return result
    return None


def rule_count() -> int:
    """Return the number of registered rules (used in tests/diagnostics)."""
    return len(_RULES)
