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
    "-f": "force the operation",
    "-v": "verbose — print more detail",
    "-h": "show help",
    "-y": "(auto-confirm — Novato never adds this for safety)",
}


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
