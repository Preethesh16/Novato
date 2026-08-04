# SPDX-License-Identifier: GPL-3.0-or-later
"""Distro-aware storage scanning and conservative cleanup suggestions.

The scanner is deliberately read-only.  It measures the user's filesystem,
looks two levels into their home directory, and identifies only cleanup jobs
that have a well-defined command supplied by the operating system.  Personal
files are reported for review but never classified as junk.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from . import sysinfo as _sysinfo
from .sysinfo import DirSize
from .storage_analyzer import Inventory, analyze_home

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
class DiskCapacity:
    """Exact capacity snapshot for one underlying filesystem."""

    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    device: str


@dataclass(frozen=True)
class StorageScan:
    """Snapshot used both before and after cleanup."""

    total_bytes: int
    used_bytes: int
    free_bytes: int
    large_dirs: list[DirSize] = field(default_factory=list)
    cache_dirs: list[DirSize] = field(default_factory=list)
    cleanup: list[CleanupItem] = field(default_factory=list)
    filesystems: list[DiskCapacity] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    system_dirs: list[DirSize] = field(default_factory=list)
    inventory: Inventory | None = None


_PACKAGE_CACHES = {
    "pacman": ("/var/cache/pacman/pkg", "sudo pacman -Sc"),
    "apt": ("/var/cache/apt/archives", "sudo apt clean"),
    "dnf": ("/var/cache/dnf", "sudo dnf clean packages"),
    "zypper": ("/var/cache/zypp/packages", "sudo zypper clean --all"),
}


def directory_bytes(path: str, *, run: Runner = _run) -> int:
    """Return allocated bytes, matching what deleting the directory can reclaim."""
    out = run(f"du -s -B1 -- {shlex.quote(path)}")
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
    aur_helper: str | None = None,
    run: Runner = _run,
    available: Callable[[str], str | None] = shutil.which,
) -> list[CleanupItem]:
    """Find measurable cleanup work, ordered from least to more consequential."""
    items: list[CleanupItem] = []

    package = _PACKAGE_CACHES.get(package_manager)
    if package:
        cache_path, command = package
        size = directory_bytes(cache_path, run=run)
        description = "Old installer files; installed programs stay installed."
        # pacman -Sc can print errors for stale DownloadUser directories and
        # the whole cache is not actually reclaimable. pacman-contrib gives us
        # a read-only dry run and an exact estimate of uninstalled archives.
        if package_manager == "pacman" and available("paccache"):
            preview = run("paccache -d -u -k 0")
            size = _paccache_saved_bytes(preview)
            command = "sudo paccache -r -u -k 0"
            description = (
                "Cached installers for packages no longer installed; current "
                "packages and programs stay available."
            )
        if size:
            items.append(CleanupItem(
                "packages", "Downloaded package cache",
                description, command, size,
            ))

    if aur_helper == "yay":
        yay_cache = _yay_build_dir(home, run=run)
        yay_size = directory_bytes(yay_cache, run=run)
        if yay_size:
            items.append(CleanupItem(
                "aur-builds", "Yay/AUR build cache",
                "Downloaded AUR source and build output. Installed programs stay "
                "installed; yay can download these files again for a future build.",
                "yay -Sc --aur", yay_size,
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
    aur_helper: str | None = None,
    run: Runner = _run,
    disk_usage: Callable = shutil.disk_usage,
    available: Callable[[str], str | None] = shutil.which,
) -> StorageScan:
    """Inspect disk capacity, large home folders, caches, and safe cleanup work."""
    cache_path = os.path.join(home, ".cache")
    large_dirs = _sysinfo.largest_dirs(home, limit=16, depth=2, run=run)
    cache_dirs = _sysinfo.largest_dirs(cache_path, limit=8, depth=2, run=run)
    # Root and home are separate filesystems on many installations. `du -x`
    # keeps this system scan off /home and virtual/network mounts.
    system_dirs = _sysinfo.largest_dirs("/", limit=12, depth=2, run=run)
    intelligence_rows = list({row.path: row for row in [*large_dirs, *cache_dirs]}.values())
    cleanup = cleanup_items(
        package_manager, home, aur_helper=aur_helper,
        run=run, available=available,
    )
    notes = _scan_notes(package_manager, run=run, available=available)
    inventory = analyze_home(home, intelligence_rows)

    # A deep scan can take long enough for a just-started cleanup (notably a
    # Trash empty operation) to finish while the scan is running.  Capacity
    # sampled before that work would make the verification result stale even
    # though the findings below are current.  Take both capacity snapshots only
    # after all potentially long-running analysis has completed.
    usage = disk_usage(home)
    filesystems = _filesystem_capacities(home, disk_usage=disk_usage)
    return StorageScan(
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        large_dirs=large_dirs,
        cache_dirs=cache_dirs,
        cleanup=cleanup,
        filesystems=filesystems,
        notes=notes,
        system_dirs=system_dirs,
        inventory=inventory,
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
        filesystems=_filesystem_capacities(path, disk_usage=disk_usage),
    )


def settle_capacity(
    scan: StorageScan,
    path: str,
    *,
    disk_usage: Callable = shutil.disk_usage,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    trash_pending: Callable[[str], bool] | None = None,
    interval: float = 0.25,
    min_wait: float = 3.0,
    stable_for: float = 1.0,
    max_wait: float = 30.0,
) -> StorageScan:
    """Refresh capacity after asynchronous Trash deletion has had time to settle.

    GVFS may return from ``gio trash --empty`` before its background worker has
    released every block.  Sample for a short bounded grace period and keep the
    newest values.  Findings remain those of the completed deep scan.
    """
    pending = trash_pending or _trash_has_payload
    trash_path = os.path.join(path, ".local", "share", "Trash")
    started = monotonic()
    last_change = started
    latest = capacity_scan(path, disk_usage=disk_usage)
    signature = _capacity_signature(latest)
    while True:
        now = monotonic()
        elapsed = now - started
        if (
            elapsed >= max(0.0, min_wait)
            and now - last_change >= max(0.0, stable_for)
            and not pending(trash_path)
        ) or elapsed >= max(0.0, max_wait):
            break
        sleep(max(0.01, interval))
        current = capacity_scan(path, disk_usage=disk_usage)
        current_signature = _capacity_signature(current)
        if current_signature != signature:
            signature = current_signature
            last_change = monotonic()
        latest = current
    return replace(
        scan,
        total_bytes=latest.total_bytes,
        used_bytes=latest.used_bytes,
        free_bytes=latest.free_bytes,
        filesystems=latest.filesystems,
    )


def _capacity_signature(scan: StorageScan) -> tuple:
    return (
        scan.total_bytes, scan.used_bytes, scan.free_bytes,
        tuple((item.device, item.used_bytes, item.free_bytes)
              for item in scan.filesystems),
    )


def _trash_has_payload(trash_path: str) -> bool:
    """Whether GVFS still has user data or expunged data waiting for deletion."""
    for name in ("files", "expunged"):
        path = os.path.join(trash_path, name)
        try:
            with os.scandir(path) as entries:
                if next(entries, None) is not None:
                    return True
        except OSError:
            continue
    return False


def _filesystem_capacities(
    home: str, *, disk_usage: Callable = shutil.disk_usage,
) -> list[DiskCapacity]:
    """Snapshot root and home once each, deduplicating a shared filesystem."""
    capacities: list[DiskCapacity] = []
    seen: set[str] = set()
    for path in (home, "/"):
        try:
            usage = disk_usage(path)
            device = str(os.stat(path).st_dev)
        except OSError:
            continue
        if device in seen:
            continue
        seen.add(device)
        capacities.append(DiskCapacity(
            path=path, total_bytes=usage.total, used_bytes=usage.used,
            free_bytes=usage.free, device=device,
        ))
    return capacities


def _paccache_saved_bytes(output: str) -> int:
    """Parse paccache's dry-run summary into an exact reclaimable byte count."""
    match = re.search(
        r"disk space saved:\s*([0-9.]+)\s*([KMGTPE]?i?B)", output,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2).upper().replace("IB", "B")
    powers = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4, "PB": 5, "EB": 6}
    return int(number * (1024 ** powers.get(unit, 0)))


def _yay_build_dir(home: str, *, run: Runner = _run) -> str:
    """Read yay's configured build directory, falling back to its standard path."""
    fallback = os.path.join(home, ".cache", "yay")
    try:
        import json

        config = json.loads(run("yay -Pg") or "{}")
        path = config.get("buildDir")
        return path if isinstance(path, str) and path else fallback
    except (ValueError, TypeError):
        return fallback


def _scan_notes(
    package_manager: str, *, run: Runner = _run,
    available: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Explain large-but-not-reclaimable or unreadable system cache content."""
    if package_manager != "pacman":
        return []
    notes: list[str] = []
    cache_path = "/var/cache/pacman/pkg"
    total = directory_bytes(cache_path, run=run)
    reclaimable = 0
    if available("paccache"):
        reclaimable = _paccache_saved_bytes(run("paccache -d -u -k 0"))
    retained = max(0, total - reclaimable)
    if retained:
        notes.append(
            f"Pacman is retaining about {format_bytes(retained)} of current or "
            "rollback package installers; Novato does not count these as safely "
            "reclaimable."
        )

    stale = 0
    try:
        with os.scandir(cache_path) as entries:
            stale = sum(
                1 for entry in entries
                if entry.name.startswith("download-")
                and entry.is_dir(follow_symlinks=False)
            )
    except OSError:
        pass
    if stale:
        notes.append(
            f"Found {stale} protected stale download director"
            f"{'y' if stale == 1 else 'ies'}. Their contents require administrator "
            "access to inspect, so they are excluded from the saving estimate."
        )
    return notes


def format_bytes(value: int) -> str:
    """Format an exact byte count for calm, beginner-friendly output."""
    number = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number:.1f} TB"
