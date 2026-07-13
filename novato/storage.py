# SPDX-License-Identifier: GPL-3.0-or-later
"""Distro-aware storage scanning and conservative cleanup suggestions.

The scanner is deliberately read-only.  It measures the user's filesystem,
looks two levels into their home directory, and identifies only cleanup jobs
that have a well-defined command supplied by the operating system.  Personal
files are reported for review but never classified as junk.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from . import sysinfo as _sysinfo
from .sysinfo import DirSize

Runner = Callable[[str], str]


def _run(command: str) -> str:
    try:
        result = subprocess.run(
            shlex.split(command), capture_output=True, text=True,
            timeout=45, check=False,
        )
        return result.stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


@dataclass(frozen=True)
class CleanupItem:
    """One safe, explainable cleanup operation Novato can offer."""

    key: str
    title: str
    description: str
    command: str
    estimated_bytes: int


@dataclass(frozen=True)
class StorageScan:
    """Snapshot used both before and after cleanup."""

    total_bytes: int
    used_bytes: int
    free_bytes: int
    large_dirs: list[DirSize] = field(default_factory=list)
    cache_dirs: list[DirSize] = field(default_factory=list)
    cleanup: list[CleanupItem] = field(default_factory=list)


_PACKAGE_CACHES = {
    "pacman": ("/var/cache/pacman/pkg", "sudo pacman -Sc"),
    "apt": ("/var/cache/apt/archives", "sudo apt clean"),
    "dnf": ("/var/cache/dnf", "sudo dnf clean packages"),
}


def directory_bytes(path: str, *, run: Runner = _run) -> int:
    """Return a directory's apparent size, or zero when it cannot be read."""
    out = run(f"du -sb -- {shlex.quote(path)}")
    first = out.strip().split(None, 1)
    if not first:
        return 0
    try:
        return max(0, int(first[0]))
    except ValueError:
        return 0


def cleanup_items(
    package_manager: str,
    home: str,
    *,
    run: Runner = _run,
    available: Callable[[str], str | None] = shutil.which,
) -> list[CleanupItem]:
    """Find measurable cleanup work, ordered from least to more consequential."""
    items: list[CleanupItem] = []

    package = _PACKAGE_CACHES.get(package_manager)
    if package:
        cache_path, command = package
        size = directory_bytes(cache_path, run=run)
        if size:
            items.append(CleanupItem(
                "packages", "Downloaded package cache",
                "Old installer files; installed programs stay installed.",
                command, size,
            ))

    trash = os.path.join(home, ".local", "share", "Trash")
    trash_size = directory_bytes(trash, run=run)
    if trash_size and available("gio"):
        items.append(CleanupItem(
            "trash", "Trash",
            "Files you previously moved to Trash. Emptying it cannot be undone.",
            "gio trash --empty", trash_size,
        ))

    journal_size = sum(directory_bytes(path, run=run) for path in (
        "/var/log/journal", "/run/log/journal",
    ))
    keep = 200 * 1024 * 1024
    if journal_size > keep and available("journalctl"):
        items.append(CleanupItem(
            "journal", "Old system logs",
            "Keeps the newest 200 MB of diagnostic logs.",
            "sudo journalctl --vacuum-size=200M", journal_size - keep,
        ))

    return items


def deep_scan(
    package_manager: str,
    home: str,
    *,
    run: Runner = _run,
    disk_usage: Callable = shutil.disk_usage,
    available: Callable[[str], str | None] = shutil.which,
) -> StorageScan:
    """Inspect disk capacity, large home folders, caches, and safe cleanup work."""
    usage = disk_usage(home)
    cache_path = os.path.join(home, ".cache")
    return StorageScan(
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        large_dirs=_sysinfo.largest_dirs(home, limit=12, depth=2, run=run),
        cache_dirs=_sysinfo.largest_dirs(cache_path, limit=6, depth=1, run=run),
        cleanup=cleanup_items(
            package_manager, home, run=run, available=available,
        ),
    )


def capacity_scan(
    path: str, *, disk_usage: Callable = shutil.disk_usage,
) -> StorageScan:
    """Return only capacity values for fast, read-only "check space" requests."""
    usage = disk_usage(path)
    return StorageScan(
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
    )


def format_bytes(value: int) -> str:
    """Format an exact byte count for calm, beginner-friendly output."""
    number = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number:.1f} TB"
