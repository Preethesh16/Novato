# SPDX-License-Identifier: GPL-3.0-or-later
"""Distro-independent, evidence-based filesystem intelligence.

This module never deletes anything. It walks the user's home filesystem without
following symlinks or crossing mounts, identifies large files, verifies large
duplicates by content hash, and classifies directories from their role rather
than their Linux distribution.
"""

from __future__ import annotations

import hashlib
import heapq
import os
import shlex
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .sysinfo import DirSize, _size_to_bytes

PROTECTED = "important"
REBUILDABLE = "rebuildable"
REVIEW = "review"


@dataclass(frozen=True)
class Finding:
    """A path plus Novato's evidence-backed interpretation of its role."""

    path: str
    size_bytes: int
    kind: str
    reason: str
    confidence: float
    age_days: int | None = None


@dataclass(frozen=True)
class ReviewCandidate:
    """One folder/file Novato can explain and optionally act on."""

    title: str
    path: str
    size_bytes: int
    category: str
    reason: str
    command: str = ""
    action: str = "review"
    age_days: int | None = None


@dataclass(frozen=True)
class DuplicateGroup:
    """Files proven byte-for-byte identical, with potential saving."""

    paths: tuple[str, ...]
    each_bytes: int
    reclaimable_bytes: int


@dataclass
class Inventory:
    """Result of the bounded local filesystem walk."""

    findings: list[Finding] = field(default_factory=list)
    largest_files: list[Finding] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    files_scanned: int = 0
    dirs_scanned: int = 0
    incomplete: bool = False
    review_candidates: list[ReviewCandidate] = field(default_factory=list)


_BUILD_PARTS = frozenset({
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".gradle", "target", "build", "cmake-build-debug",
    "cmake-build-release", ".parcel-cache", ".next", ".venv", "venv",
})
_PERSONAL_ROOTS = frozenset({
    "documents", "pictures", "photos", "music", "videos", "desktop",
    "projects", "workspace", "workspaces", "androidstudioprojects",
})
_SETTINGS_ROOTS = frozenset({
    ".config", ".ssh", ".gnupg", ".password-store", ".mozilla",
})
_TOOLCHAIN_PARTS = frozenset({
    "sdk", "android", ".vscode", ".local", "steam", "flatpak",
})
_ARCHIVE_SUFFIXES = frozenset({
    ".iso", ".img", ".zip", ".7z", ".rar", ".tar", ".gz", ".xz",
    ".bz2", ".zst", ".apk", ".appimage",
})


def classify_path(path: str, home: str, *, is_file: bool = False,
                  age_days: int | None = None) -> tuple[str, str, float]:
    """Infer a path's role from filesystem conventions and local evidence."""
    try:
        relative = Path(path).resolve(strict=False).relative_to(
            Path(home).resolve(strict=False)
        )
        parts = [part.lower() for part in relative.parts]
    except (OSError, ValueError):
        parts = [part.lower() for part in Path(path).parts]
    part_set = set(parts)
    name = parts[-1] if parts else ""

    if ".cache" in part_set:
        return (
            REBUILDABLE,
            "Application cache: normally downloadable or regeneratable, but "
            "may contain offline app data, so confirmation is still required.",
            0.84,
        )
    if part_set & _BUILD_PARTS:
        return (
            REBUILDABLE,
            "Generated dependency/build output; source files should remain, but "
            "rebuilding may take time or require downloads.",
            0.88,
        )
    if name in ("dist", "out") and not is_file:
        return REBUILDABLE, "Likely generated build output; review before removal.", 0.72
    if part_set & _SETTINGS_ROOTS:
        return PROTECTED, "Application or security configuration; do not treat as junk.", 0.96
    if ".git" in part_set or os.path.isdir(os.path.join(path, ".git")):
        return PROTECTED, "Source repository; project history and work may be unique.", 0.97
    if parts and parts[0] == "downloads":
        old = age_days is not None and age_days >= 90
        reason = (
            "Old download; it may be replaceable, but only you can decide whether "
            "it is still needed." if old else
            "Downloaded content; review manually because it may be important."
        )
        return REVIEW, reason, 0.75 if old else 0.62
    if part_set & _TOOLCHAIN_PARTS:
        return (
            REVIEW,
            "Toolchain/application data: often reinstallable, but removing it can "
            "break development tools or require a large download.",
            0.78,
        )
    if is_file and Path(name).suffix.lower() in _ARCHIVE_SUFFIXES:
        return (
            REVIEW,
            "Archive/installer image; potentially replaceable, but not automatically junk.",
            0.72,
        )
    if parts and parts[0] in _PERSONAL_ROOTS:
        return PROTECTED, "Personal/project content; Novato protects it from cleanup.", 0.95
    return REVIEW, "Large data with no safe automatic classification; review manually.", 0.5


def analyze_home(
    home: str,
    large_dirs: Iterable[DirSize],
    *,
    max_files: int = 1_000_000,
    max_seconds: float = 60.0,
    duplicate_min_bytes: int = 50 * 1024**2,
    largest_limit: int = 15,
) -> Inventory:
    """Walk home locally and produce bounded, evidence-backed findings."""
    inventory = Inventory()
    for row in large_dirs:
        kind, reason, confidence = classify_path(row.path, home)
        inventory.findings.append(Finding(
            row.path, int(_size_to_bytes(row.size)), kind, reason, confidence,
        ))

    try:
        home_device = os.stat(home, follow_symlinks=False).st_dev
    except OSError:
        return inventory

    started = time.monotonic()
    largest: list[tuple[int, str, float]] = []
    duplicate_candidates: dict[int, list[tuple[str, tuple[int, int]]]] = {}
    generated_stats: dict[str, tuple[int, float]] = {}
    sdk_stats: dict[tuple[str, str, str], tuple[int, float]] = {}
    stop = False

    for root, dirs, files in os.walk(home, topdown=True, followlinks=False):
        inventory.dirs_scanned += 1
        kept_dirs = []
        for dirname in dirs:
            full = os.path.join(root, dirname)
            try:
                info = os.stat(full, follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode) and info.st_dev == home_device:
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        for filename in files:
            path = os.path.join(root, filename)
            try:
                info = os.stat(path, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_dev != home_device:
                continue
            inventory.files_scanned += 1
            item = (info.st_size, path, info.st_mtime)
            if len(largest) < largest_limit:
                heapq.heappush(largest, item)
            elif item[0] > largest[0][0]:
                heapq.heapreplace(largest, item)
            if info.st_size >= duplicate_min_bytes:
                group = duplicate_candidates.setdefault(info.st_size, [])
                if len(group) < 32:
                    group.append((path, (info.st_dev, info.st_ino)))
            generated = _generated_root(path, home)
            if generated:
                old_size, old_time = generated_stats.get(generated, (0, 0.0))
                generated_stats[generated] = (
                    old_size + info.st_size, max(old_time, info.st_mtime),
                )
            sdk_component = _sdk_component(path, home)
            if sdk_component:
                old_size, old_time = sdk_stats.get(sdk_component, (0, 0.0))
                sdk_stats[sdk_component] = (
                    old_size + info.st_size, max(old_time, info.st_mtime),
                )

            if inventory.files_scanned >= max_files or (
                inventory.files_scanned % 256 == 0
                and time.monotonic() - started >= max_seconds
            ):
                inventory.incomplete = True
                dirs[:] = []
                stop = True
                break
        if stop:
            break

    now = time.time()
    for size, path, modified in sorted(largest, reverse=True):
        age_days = max(0, int((now - modified) / 86400))
        kind, reason, confidence = classify_path(
            path, home, is_file=True, age_days=age_days,
        )
        if age_days >= 180:
            reason += f" Last modified about {age_days} days ago."
        inventory.largest_files.append(Finding(
            path, size, kind, reason, confidence, age_days,
        ))

    inventory.duplicates = _verified_duplicates(duplicate_candidates)
    existing = {finding.path: finding for finding in inventory.findings}
    for path, (size, modified) in generated_stats.items():
        if size < 25 * 1024**2:
            continue
        kind, reason, confidence = classify_path(path, home)
        current = existing.get(path)
        age_days = max(0, int((now - modified) / 86400)) if modified else None
        finding = Finding(path, max(size, current.size_bytes if current else 0),
                          kind, reason, confidence, age_days)
        existing[path] = finding
    inventory.findings = list(existing.values())
    inventory.findings.sort(key=lambda finding: finding.size_bytes, reverse=True)
    inventory.review_candidates = _build_review_candidates(
        inventory, home, sdk_stats=sdk_stats, now=now,
    )
    return inventory


def _generated_root(path: str, home: str) -> str:
    """Return the nearest cache/build root that owns a generated file."""
    try:
        relative = Path(path).relative_to(home)
    except ValueError:
        return ""
    parts = relative.parts
    lowered = [part.lower() for part in parts]
    if ".cache" in lowered:
        index = lowered.index(".cache")
        # Attribute cache usage to the application directly below ~/.cache.
        end = min(len(parts), index + 2)
        return os.path.join(home, *parts[:end])
    if ".gradle" in lowered:
        index = lowered.index(".gradle")
        if index + 1 < len(parts) and lowered[index + 1] in {
            "caches", "daemon", "native",
        }:
            return os.path.join(home, *parts[:index + 2])
        if lowered[index + 1:index + 3] == ["wrapper", "dists"]:
            return os.path.join(home, *parts[:index + 3])
        # A project-local .gradle folder is generated; ~/.gradle itself may
        # contain properties/credentials, so never offer the whole root.
        if index > 0:
            return os.path.join(home, *parts[:index + 1])
        return ""
    indexes = [index for index, part in enumerate(lowered) if part in _BUILD_PARTS]
    if indexes:
        index = indexes[-1]
        return os.path.join(home, *parts[:index + 1])
    return ""


def _sdk_component(path: str, home: str) -> tuple[str, str, str] | None:
    """Identify Android SDK packages and virtual devices from their structure."""
    try:
        relative = Path(path).relative_to(home)
    except ValueError:
        return None
    parts = list(relative.parts)
    lowered = [part.lower() for part in parts]

    # ~/.android/avd/Phone.avd/... -> one removable virtual device.
    if len(parts) >= 3 and lowered[:2] == [".android", "avd"]:
        for index in range(2, len(parts)):
            if lowered[index].endswith(".avd"):
                name = parts[index][:-4]
                root = os.path.join(home, *parts[:index + 1])
                return root, "emulator", name

    try:
        sdk_index = lowered.index("sdk")
    except ValueError:
        return None
    if sdk_index == 0 or lowered[sdk_index - 1] != "android":
        return None
    tail = parts[sdk_index + 1:]
    if len(tail) < 2:
        return None
    category = tail[0].lower()
    depths = {
        "platforms": 2, "build-tools": 2, "ndk": 2, "sources": 2,
        "system-images": 4,
    }
    depth = depths.get(category)
    if depth is None or len(tail) < depth:
        return None
    component = tail[:depth]
    root = os.path.join(home, *parts[:sdk_index + 1], *component)
    package_id = ";".join(component)
    return root, "sdk", package_id


def _build_review_candidates(
    inventory: Inventory,
    home: str,
    *,
    sdk_stats: dict[tuple[str, str, str], tuple[int, float]],
    now: float,
) -> list[ReviewCandidate]:
    candidates: list[ReviewCandidate] = []
    gio = shutil.which("gio")

    for finding in inventory.findings:
        if finding.kind != REBUILDABLE or not _actionable_generated(finding.path, home):
            continue
        command = shlex.join([gio, "trash", finding.path]) if gio else ""
        candidates.append(ReviewCandidate(
            title=os.path.basename(finding.path) or finding.path,
            path=finding.path,
            size_bytes=finding.size_bytes,
            category="rebuildable folder",
            reason=finding.reason,
            command=command,
            action="move to Trash" if command else "review",
            age_days=finding.age_days,
        ))

    sdkmanager = _android_tool(home, "sdkmanager")
    avdmanager = _android_tool(home, "avdmanager")
    for (path, component_type, identifier), (size, modified) in sdk_stats.items():
        age_days = max(0, int((now - modified) / 86400)) if modified else None
        if component_type == "sdk":
            command = shlex.join([sdkmanager, "--uninstall", identifier]) \
                if sdkmanager else ""
            reason = (
                "Installed Android SDK component. Projects may reference this exact "
                "version, so Novato will only use sdkmanager after you choose it."
            )
            title = f"Android SDK: {identifier}"
            action = "uninstall with sdkmanager" if command else "review"
        else:
            command = shlex.join([avdmanager, "delete", "avd", "-n", identifier]) \
                if avdmanager else ""
            reason = (
                "Android virtual device data. Deleting it removes that emulator's "
                "apps and settings, but not your project source code."
            )
            title = f"Android emulator: {identifier}"
            action = "delete with avdmanager" if command else "review"
        candidates.append(ReviewCandidate(
            title, path, size, component_type, reason, command, action, age_days,
        ))

    # Old large archives/installers are offered via Trash, never permanent delete.
    for finding in inventory.largest_files:
        if finding.kind != REVIEW or (finding.age_days or 0) < 90:
            continue
        if Path(finding.path).suffix.lower() not in _ARCHIVE_SUFFIXES:
            continue
        command = shlex.join([gio, "trash", finding.path]) if gio else ""
        candidates.append(ReviewCandidate(
            os.path.basename(finding.path), finding.path, finding.size_bytes,
            "old archive", finding.reason, command,
            "move to Trash" if command else "review", finding.age_days,
        ))

    # A content hash proves duplication. Keep the most important-looking copy
    # and offer the others individually, still through Trash.
    for group in inventory.duplicates:
        ranked = sorted(
            group.paths,
            key=lambda path: classify_path(path, home, is_file=True)[2],
            reverse=True,
        )
        keeper = ranked[0]
        for path in ranked[1:]:
            command = shlex.join([gio, "trash", path]) if gio else ""
            candidates.append(ReviewCandidate(
                os.path.basename(path), path, group.each_bytes, "exact duplicate",
                f"Content hash matches {keeper}. Keeping at least one copy is required.",
                command, "move duplicate to Trash" if command else "review",
            ))

    # Larger and older candidates first; stable de-duplication by real path.
    unique: dict[str, ReviewCandidate] = {}
    for candidate in candidates:
        unique.setdefault(os.path.realpath(candidate.path), candidate)
    return sorted(
        unique.values(),
        key=lambda item: (item.age_days or 0, item.size_bytes), reverse=True,
    )[:40]


def _actionable_generated(path: str, home: str) -> bool:
    """Allow only conventional generated/cache roots strictly inside home."""
    if os.path.islink(path) or not os.path.isdir(path):
        return False
    real_home = os.path.realpath(home)
    real_path = os.path.realpath(path)
    if real_path == real_home or not real_path.startswith(real_home + os.sep):
        return False
    relative = Path(real_path).relative_to(real_home)
    lowered = [part.lower() for part in relative.parts]
    basename = lowered[-1] if lowered else ""
    if len(lowered) == 2 and lowered[0] == ".cache":
        return lowered[1] != "yay"  # yay has a safer native cleanup flow.
    if basename in _BUILD_PARTS or basename in {"dist", "out"}:
        return True
    if ".gradle" in lowered and basename in {"caches", "daemon", "native", "dists"}:
        return True
    return False


def _android_tool(home: str, name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    base = Path(home) / "Android" / "Sdk" / "cmdline-tools"
    if not base.is_dir():
        return ""
    matches = sorted(base.glob(f"*/bin/{name}"), reverse=True)
    return str(matches[0]) if matches else ""


def _verified_duplicates(
    candidates: dict[int, list[tuple[str, tuple[int, int]]]],
    *, max_files_to_hash: int = 160,
) -> list[DuplicateGroup]:
    """Hash only same-sized large files; size alone is never called a duplicate."""
    groups: list[DuplicateGroup] = []
    hashed = 0
    for size, entries in sorted(candidates.items(), reverse=True):
        unique_inodes: dict[tuple[int, int], str] = {}
        for path, inode in entries:
            unique_inodes.setdefault(inode, path)
        if len(unique_inodes) < 2:
            continue
        by_digest: dict[str, list[str]] = {}
        for path in unique_inodes.values():
            if hashed >= max_files_to_hash:
                break
            digest = _sha256(path)
            hashed += 1
            if digest:
                by_digest.setdefault(digest, []).append(path)
        for paths in by_digest.values():
            if len(paths) > 1:
                groups.append(DuplicateGroup(
                    tuple(paths), size, size * (len(paths) - 1),
                ))
        if hashed >= max_files_to_hash:
            break
    groups.sort(key=lambda group: group.reclaimable_bytes, reverse=True)
    return groups[:8]


def _sha256(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""
