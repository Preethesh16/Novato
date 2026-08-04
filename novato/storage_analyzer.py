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
    recommended: bool = False


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
    ".ruff_cache", ".tox", "target", "build", "cmake-build-debug",
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
# Cache locations used by language/tool ecosystems independently of the Linux
# distribution.  Only these cache subtrees are rebuildable; their parent
# directories can also contain configuration, credentials, or installed tools.
_ECOSYSTEM_CACHE_PATTERNS = (
    (".npm", "_cacache"),
    (".npm", "_npx"),
    (".yarn", "berry", "cache"),
    (".cargo", "registry", "cache"),
    (".cargo", "registry", "index"),
    (".cargo", "git", "db"),
    (".gradle", "caches"),
    (".gradle", "daemon"),
    (".gradle", "native"),
    (".gradle", "wrapper", "dists"),
)
_SAFE_APP_CACHE_NAMES = frozenset({
    "pip", "uv", "pnpm", "ms-playwright", "playwright", "thumbnails",
    "vscode-cpptools", "mesa_shader_cache",
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

    if _matching_cache_root(parts):
        return (
            REBUILDABLE,
            "Downloaded developer-tool cache. It can be recreated when the tool "
            "next needs it; configuration and project source are outside this folder.",
            0.92,
        )
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
    if ".gradle" in part_set and parts and parts[0] != ".gradle":
        return (
            REBUILDABLE,
            "Project-local Gradle output; it can be regenerated from the project.",
            0.9,
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
    trash_root = os.path.realpath(os.path.join(home, ".local", "share", "Trash"))
    largest: list[tuple[int, str, float]] = []
    duplicate_candidates: dict[int, list[tuple[str, tuple[int, int]]]] = {}
    generated_links: dict[
        str, dict[tuple[int, int], tuple[int, int, int, float]]
    ] = {}
    sdk_links: dict[
        tuple[str, str, str], dict[tuple[int, int], tuple[int, int, int, float]]
    ] = {}
    stop = False

    for root, dirs, files in os.walk(home, topdown=True, followlinks=False):
        inventory.dirs_scanned += 1
        kept_dirs = []
        for dirname in dirs:
            full = os.path.join(root, dirname)
            real_full = os.path.realpath(full)
            if real_full == trash_root or real_full.startswith(trash_root + os.sep):
                continue
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
                inode = (info.st_dev, info.st_ino)
                links = generated_links.setdefault(generated, {})
                count, blocks, link_count, modified = links.get(
                    inode, (0, info.st_blocks * 512, info.st_nlink, 0.0),
                )
                links[inode] = (
                    count + 1, blocks, link_count, max(modified, info.st_mtime),
                )
            sdk_component = _sdk_component(path, home)
            if sdk_component:
                inode = (info.st_dev, info.st_ino)
                links = sdk_links.setdefault(sdk_component, {})
                count, blocks, link_count, modified = links.get(
                    inode, (0, info.st_blocks * 512, info.st_nlink, 0.0),
                )
                links[inode] = (
                    count + 1, blocks, link_count, max(modified, info.st_mtime),
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
    generated_stats = _reclaimable_link_stats(generated_links)
    sdk_stats = _reclaimable_link_stats(sdk_links)
    existing = {finding.path: finding for finding in inventory.findings}
    for path in list(existing):
        if _actionable_generated(path, home) and path not in generated_stats:
            existing.pop(path)
    for path, (size, modified) in generated_stats.items():
        kind, reason, confidence = classify_path(path, home)
        age_days = max(0, int((now - modified) / 86400)) if modified else None
        finding = Finding(path, size, kind, reason, confidence, age_days)
        existing[path] = finding
    inventory.findings = list(existing.values())
    inventory.findings.sort(key=lambda finding: finding.size_bytes, reverse=True)
    inventory.review_candidates = _build_review_candidates(
        inventory, home, sdk_stats=sdk_stats, now=now,
    )
    return inventory


def _reclaimable_link_stats(roots):
    """Count an inode only when removing this one root releases its blocks.

    If a hard link exists outside the candidate root (including another cache
    or protected data), deleting this root cannot reclaim that inode's blocks.
    """
    result = {}
    for root, inodes in roots.items():
        size = 0
        modified = 0.0
        for count, blocks, link_count, newest in inodes.values():
            modified = max(modified, newest)
            if count >= link_count:
                size += blocks
        result[root] = (size, modified)
    return result


def _generated_root(path: str, home: str) -> str:
    """Return the nearest cache/build root that owns a generated file."""
    try:
        relative = Path(path).relative_to(home)
    except ValueError:
        return ""
    parts = relative.parts
    lowered = [part.lower() for part in parts]
    cache_root = _matching_cache_root(lowered)
    if cache_root:
        return os.path.join(home, *parts[:cache_root])
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
        # Use the outermost generated tree. Offering both a parent node_modules
        # and nested build/node_modules paths creates overlapping actions; once
        # the parent moves, every child command becomes stale.
        index = indexes[0]
        return os.path.join(home, *parts[:index + 1])
    return ""


def _matching_cache_root(parts: list[str]) -> int:
    """Return the component count through a known ecosystem cache, else zero."""
    lowered = [part.lower() for part in parts]
    for pattern in _ECOSYSTEM_CACHE_PATTERNS:
        width = len(pattern)
        for start in range(0, len(lowered) - width + 1):
            if tuple(lowered[start:start + width]) == pattern:
                return start + width
    return 0


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
        if (
            finding.kind != REBUILDABLE
            or finding.size_bytes < 25 * 1024**2
            or not _actionable_generated(finding.path, home)
        ):
            continue
        command = shlex.join([gio, "trash", finding.path]) if gio else ""
        download_cache = _is_download_cache_root(finding.path, home)
        candidates.append(ReviewCandidate(
            title=os.path.basename(finding.path) or finding.path,
            path=finding.path,
            size_bytes=finding.size_bytes,
            category="download cache" if download_cache else "rebuildable folder",
            reason=finding.reason,
            command=command,
            action="move to Trash" if command else "review",
            age_days=finding.age_days,
            recommended=bool(command and download_cache),
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
    candidates = _remove_overlapping_candidates(list(unique.values()))
    return sorted(candidates, key=_candidate_priority, reverse=True)[:40]


def _remove_overlapping_candidates(
    candidates: list[ReviewCandidate],
) -> list[ReviewCandidate]:
    """Remove child actions already covered by an actionable parent folder."""
    by_depth = sorted(
        candidates,
        key=lambda item: (len(Path(item.path).parts), -item.size_bytes),
    )
    selected: list[ReviewCandidate] = []
    for candidate in by_depth:
        real_path = os.path.realpath(candidate.path)
        covered = False
        if candidate.action.startswith("move"):
            for parent in selected:
                if not parent.command or not parent.action.startswith("move"):
                    continue
                real_parent = os.path.realpath(parent.path)
                try:
                    covered = os.path.commonpath([real_parent, real_path]) == real_parent
                except ValueError:
                    covered = False
                if covered and real_path != real_parent:
                    break
        if not covered:
            selected.append(candidate)
    return selected


def _candidate_priority(item: ReviewCandidate) -> tuple[int, int, int]:
    """Put low-risk, high-return actions before merely old or interesting data."""
    return (
        1 if item.recommended else 0,
        item.size_bytes,
        item.age_days or 0,
    )


def _is_download_cache_root(path: str, home: str) -> bool:
    """True only for structurally known download caches.

    A generic ``~/.cache/<app>`` directory is intentionally excluded: browsers,
    media apps, and offline-first tools can keep useful session/offline data
    there even though the directory is named "cache".
    """
    try:
        relative = Path(os.path.realpath(path)).relative_to(os.path.realpath(home))
    except ValueError:
        return False
    lowered = [part.lower() for part in relative.parts]
    if _matching_cache_root(lowered) == len(lowered):
        return True
    return (
        len(lowered) == 2
        and lowered[0] == ".cache"
        and lowered[1] in _SAFE_APP_CACHE_NAMES
    )


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
    if _matching_cache_root(lowered) == len(lowered):
        return True
    if len(lowered) == 2 and lowered[0] == ".cache":
        return lowered[1] != "yay"  # yay has a safer native cleanup flow.
    if basename in _BUILD_PARTS or basename in {"dist", "out"}:
        return True
    if basename == ".gradle" and lowered[0] != ".gradle":
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
