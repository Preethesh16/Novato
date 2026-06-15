# SPDX-License-Identifier: GPL-3.0-or-later
"""Teaching mode (`/explain`).

When teaching mode is on, every action Novato takes is accompanied by a short,
respectful, plain-English explanation of the command and its flags. The golden
rule: assume the reader has never used Linux before, but never be condescending.

This module turns a command string into an ordered ``token -> meaning`` mapping
the presenter renders. It is pure data + small heuristics, so it works in Basic
mode with zero AI and is fully unit-testable.
"""

from __future__ import annotations

from collections import OrderedDict

# What each package manager *is*, in beginner terms.
_PM_MEANING = {
    "pacman": "Arch Linux's package manager (like an app store)",
    "yay": "an AUR helper — installs community packages for Arch",
    "paru": "an AUR helper — installs community packages for Arch",
    "apt": "Ubuntu/Debian's package manager",
    "apt-get": "Ubuntu/Debian's package manager (older command)",
    "dnf": "Fedora's package manager",
    "zypper": "openSUSE's package manager",
    "pip": "Python's package installer",
    "npm": "Node.js's package installer",
    "flatpak": "a universal package system that works across distros",
}

# Common flags and what they mean, per relevant command. Looked up as
# (command, flag) first, then a generic fallback by flag alone.
_FLAG_MEANING = {
    ("pacman", "-S"): "Sync — download & install from the official servers",
    ("pacman", "-Ss"): "Search the repositories for a package",
    ("pacman", "-R"): "Remove an installed package",
    ("pacman", "-Syu"): "Refresh package lists and upgrade everything",
    ("pacman", "--needed"): "skip packages that are already installed",
    ("apt", "install"): "install the named package",
    ("apt", "remove"): "uninstall the named package",
    ("apt", "update"): "refresh the list of available packages",
    ("apt", "upgrade"): "install available updates",
    ("dnf", "install"): "install the named package",
    ("zypper", "install"): "install the named package",
    ("pip", "install"): "download & install a Python library",
    ("npm", "install"): "download & install a Node package",
}

# Generic flag glossary (used when no command-specific meaning is found).
_GENERIC_FLAGS = {
    "-S": "Sync — download & install from official servers",
    "install": "install the named package",
    "remove": "uninstall the named package",
    "search": "search for a package",
    "-r": "recursive / remove (depends on the command)",
    "-R": "recursive (apply to a folder and everything inside)",
    "-f": "force the operation",
    "-v": "verbose — print more detail",
    "-h": "show help (often combined with -l as human-readable sizes)",
    "-l": "long format — one item per line, with details",
    "-a": "all — include hidden items",
    "-la": "all items, in detailed long format",
    "-p": "create parent folders as needed / preserve",
    "-y": "(auto-confirm — Novato never adds this for safety)",
    "--help": "show built-in help for this command",
}

# What common, everyday commands *are*, in beginner terms. Powers the
# ``/explain <command>`` feature so a newcomer can ask about ANY command, not
# just the ones Novato runs for them.
_COMMAND_MEANING = {
    "ls": "list what's in a folder",
    "cd": "change directory — move into a folder",
    "pwd": "print the folder you're currently in",
    "mkdir": "make a new folder",
    "rmdir": "remove an empty folder",
    "rm": "remove (delete) files — permanently, there's no undo",
    "cp": "copy files or folders",
    "mv": "move or rename files or folders",
    "touch": "create a new empty file (or update its timestamp)",
    "cat": "print a file's contents to the screen",
    "less": "scroll through a long file one screen at a time",
    "head": "show the first lines of a file",
    "tail": "show the last lines of a file",
    "nano": "a simple, beginner-friendly text editor",
    "vim": "a powerful (but tricky) text editor — quit with :q",
    "grep": "search for text inside files",
    "find": "search for files by name or other criteria",
    "which": "show the full path to a command",
    "chmod": "change a file's permissions (who can read/write/run it)",
    "chown": "change who owns a file",
    "sudo": "run as administrator (needed for system changes)",
    "ps": "list running processes (programs)",
    "top": "watch live CPU and memory usage",
    "kill": "stop a running program by its process number (PID)",
    "killall": "stop every process with a given name",
    "df": "show how much disk space is free",
    "du": "show how much space files/folders use",
    "free": "show how much memory (RAM) is in use",
    "ping": "check whether you can reach a server over the network",
    "curl": "fetch data from a web address",
    "wget": "download a file from a web address",
    "ssh": "log into another computer over the network",
    "tar": "bundle or unpack .tar archives",
    "unzip": "unpack a .zip file",
    "zip": "bundle files into a .zip archive",
    "echo": "print text back to the screen",
    "man": "open the full manual for a command (quit with q)",
    "whoami": "show the username you're logged in as",
    "date": "show the current date and time",
    "history": "show the commands you've run before",
    "clear": "wipe the terminal screen clean",
}

# Per-command flag meanings beyond the package-manager set above.
_CMD_FLAGS = {
    ("ls", "-l"): "long format — show details (permissions, size, date)",
    ("ls", "-a"): "show hidden files too (names starting with a dot)",
    ("ls", "-la"): "show all files, with full details",
    ("ls", "-lh"): "details, with human-readable sizes (KB/MB/GB)",
    ("rm", "-r"): "recursive — also delete folders and their contents",
    ("rm", "-f"): "force — don't ask for confirmation (dangerous)",
    ("rm", "-rf"): "force-delete a folder and everything in it (very dangerous)",
    ("cp", "-r"): "recursive — copy a whole folder",
    ("mkdir", "-p"): "create parent folders as needed, no error if it exists",
    ("chmod", "+x"): "make the file executable (runnable as a program)",
    ("grep", "-r"): "search recursively through every file in a folder",
    ("grep", "-i"): "ignore upper/lower case while searching",
    ("tar", "-xzf"): "extract a gzip-compressed .tar.gz archive",
    ("tar", "-czf"): "create a gzip-compressed .tar.gz archive",
    ("df", "-h"): "human-readable sizes (GB/MB instead of raw blocks)",
    ("du", "-sh"): "one total size per item, human-readable",
    ("ping", "-c"): "send a fixed number of pings, then stop",
}

# Well-known filesystem locations, explained for newcomers.
_PATH_MEANING = {
    "/etc": "the system configuration folder",
    "/var": "variable data — logs, caches, mail, etc.",
    "/var/log": "where system and application logs live",
    "/home": "where every user's personal folder lives",
    "/usr": "installed programs and their support files",
    "/usr/bin": "where most installed programs live",
    "/bin": "essential system programs",
    "/tmp": "temporary files (wiped on reboot)",
    "/dev": "device files (disks, terminals, etc.)",
    "/proc": "live system and process information",
    "/root": "the administrator's home folder",
    "/boot": "files needed to start (boot) the system",
    "~": "your home folder",
    "/": "the very top of the filesystem (the root)",
    ".": "the current folder",
    "..": "the folder one level up",
}


def _explain_chmod_mode(token: str) -> "str | None":
    """Explain a numeric chmod mode like ``755`` in beginner terms, or None.

    Each octal digit is owner / group / others, summed from read(4)+write(2)+
    execute(1). We translate the common ones rather than dump the bit math.
    """
    if not (token.isdigit() and len(token) in (3, 4)):
        return None
    digits = token[-3:]  # ignore a leading special-bits digit if present
    names = ("owner", "group", "others")
    parts = []
    for who, d in zip(names, digits):
        if d not in "01234567":
            return None
        bits = int(d)
        perms = []
        if bits & 4:
            perms.append("read")
        if bits & 2:
            perms.append("write")
        if bits & 1:
            perms.append("run")
        parts.append(f"{who}: {'/'.join(perms) if perms else 'nothing'}")
    return "permissions — " + ", ".join(parts)


class Teacher:
    """Produces plain-English explanations for commands."""

    def explain_command(self, command: str, *, package: str = "") -> "OrderedDict[str, str]":
        """Break a command into a token -> beginner-meaning mapping.

        The returned mapping preserves a sensible reading order: ``sudo`` first,
        then the program, then its flags/subcommands, then the package.
        """
        parts: "OrderedDict[str, str]" = OrderedDict()
        tokens = command.split()
        if not tokens:
            return parts

        if tokens[0] == "sudo":
            parts["sudo"] = "run as administrator (needed for system changes)"
            tokens = tokens[1:]
        if not tokens:
            return parts

        program = tokens[0]
        if program in _PM_MEANING:
            parts[program] = _PM_MEANING[program]

        # Explain each remaining flag/subcommand we recognise.
        for tok in tokens[1:]:
            if package and tok == package:
                continue
            meaning = _FLAG_MEANING.get((program, tok)) or _GENERIC_FLAGS.get(tok)
            if meaning and tok not in parts:
                parts[tok] = meaning

        if package:
            parts[package] = "the exact package name being installed"
        return parts

    def explain_package(self, package: str, description: str = "") -> str:
        """One-line, beginner-friendly note about why this package fits."""
        if description:
            return f"{package} — {description}"
        return package

    def explain_arbitrary_command(self, command: str) -> "OrderedDict[str, str]":
        """Explain ANY command the user asks about, token by token.

        Unlike :meth:`explain_command` (tuned for install commands), this powers
        ``/explain ls -la /etc`` — it knows everyday programs, their common
        flags, and well-known paths. Returns a token -> plain-English mapping in
        reading order; unknown tokens are simply left out rather than guessed.
        """
        parts: "OrderedDict[str, str]" = OrderedDict()
        tokens = command.split()
        if not tokens:
            return parts

        if tokens[0] == "sudo":
            parts["sudo"] = _COMMAND_MEANING["sudo"]
            tokens = tokens[1:]
        if not tokens:
            return parts

        program = tokens[0]
        prog_meaning = (
            _COMMAND_MEANING.get(program)
            or _PM_MEANING.get(program)
        )
        if prog_meaning:
            parts[program] = prog_meaning

        for tok in tokens[1:]:
            if tok in parts:
                continue
            meaning = (
                _CMD_FLAGS.get((program, tok))
                or _FLAG_MEANING.get((program, tok))
                or _GENERIC_FLAGS.get(tok)
                or _PATH_MEANING.get(tok)
            )
            if meaning is None and program == "chmod":
                meaning = _explain_chmod_mode(tok)
            if meaning is None and tok.startswith("-"):
                meaning = "an option that changes how the command behaves"
            if meaning is None and tok.startswith("/"):
                meaning = "a file or folder path on your system"
            if meaning:
                parts[tok] = meaning
        return parts
