"""Tests for distro-independent filesystem intelligence."""

from __future__ import annotations

import os

import pytest

from novato.storage_analyzer import (
    PROTECTED,
    REBUILDABLE,
    REVIEW,
    analyze_home,
    classify_path,
)
from novato import storage_analyzer
from novato.sysinfo import DirSize


@pytest.mark.parametrize("relative,kind", [
    ("Projects/novato", PROTECTED),
    ("Documents/report.pdf", PROTECTED),
    ("Documents/old-backup.zip", REVIEW),
    (".config/Code/settings.json", PROTECTED),
    (".cache/yay/package/src/object.o", REBUILDABLE),
    ("Projects/site/node_modules/library.js", REBUILDABLE),
    ("Downloads/old-linux.iso", REVIEW),
    ("Android/Sdk/platforms", REVIEW),
])
def test_classification_uses_role_not_distro(tmp_path, relative, kind):
    path = tmp_path / relative
    assert classify_path(str(path), str(tmp_path), is_file=True)[0] == kind


def test_analyzer_hash_verifies_duplicates_and_finds_large_files(tmp_path):
    cache = tmp_path / ".cache" / "builder"
    cache.mkdir(parents=True)
    first = cache / "copy-one.bin"
    second = cache / "copy-two.bin"
    different = cache / "different.bin"
    first.write_bytes(b"same-content" * 100)
    second.write_bytes(b"same-content" * 100)
    different.write_bytes(b"other-content" * 100)

    inventory = analyze_home(
        str(tmp_path), [DirSize("3G", str(cache))],
        duplicate_min_bytes=1, max_seconds=5,
    )
    assert inventory.files_scanned == 3
    assert inventory.findings[0].kind == REBUILDABLE
    assert len(inventory.duplicates) == 1
    assert set(inventory.duplicates[0].paths) == {str(first), str(second)}
    assert inventory.largest_files


def test_analyzer_does_not_follow_symlinks_or_cross_filesystems(tmp_path):
    outside = tmp_path.parent / "outside-storage-scan"
    outside.mkdir(exist_ok=True)
    (outside / "secret.bin").write_bytes(b"private")
    os.symlink(outside, tmp_path / "linked-outside")

    inventory = analyze_home(str(tmp_path), [], duplicate_min_bytes=1)
    paths = {finding.path for finding in inventory.largest_files}
    assert str(outside / "secret.bin") not in paths


def test_analyzer_marks_a_bounded_scan_incomplete(tmp_path):
    for number in range(5):
        (tmp_path / f"file-{number}").write_text(str(number))
    inventory = analyze_home(str(tmp_path), [], max_files=2)
    assert inventory.files_scanned == 2
    assert inventory.incomplete is True


def test_analyzer_aggregates_nested_build_artifacts(tmp_path):
    modules = tmp_path / "Projects" / "web" / "node_modules"
    modules.mkdir(parents=True)
    with open(modules / "dependency.bin", "wb") as handle:
        handle.truncate(30 * 1024**2)

    inventory = analyze_home(str(tmp_path), [], max_seconds=5)
    generated = next(
        finding for finding in inventory.findings if finding.path == str(modules)
    )
    assert generated.kind == REBUILDABLE
    assert generated.size_bytes == 30 * 1024**2


@pytest.mark.parametrize("relative", [
    ".npm/_cacache/content-v2/blob",
    ".npm/_npx/job/node_modules/tool/index.js",
    ".yarn/berry/cache/library.zip",
    ".cargo/registry/cache/crate.tar.gz",
    ".cargo/git/db/repository/objects/pack",
    ".gradle/wrapper/dists/gradle/bin/gradle",
])
def test_analyzer_finds_cross_distro_ecosystem_caches(tmp_path, relative):
    cached = tmp_path / relative
    cached.parent.mkdir(parents=True, exist_ok=True)
    with open(cached, "wb") as handle:
        handle.truncate(30 * 1024**2)

    inventory = analyze_home(str(tmp_path), [], max_seconds=5)
    candidates = {item.path: item for item in inventory.review_candidates}
    expected_roots = {
        ".npm/_cacache/content-v2/blob": ".npm/_cacache",
        ".npm/_npx/job/node_modules/tool/index.js": ".npm/_npx",
        ".yarn/berry/cache/library.zip": ".yarn/berry/cache",
        ".cargo/registry/cache/crate.tar.gz": ".cargo/registry/cache",
        ".cargo/git/db/repository/objects/pack": ".cargo/git/db",
        ".gradle/wrapper/dists/gradle/bin/gradle": ".gradle/wrapper/dists",
    }
    root = str(tmp_path / expected_roots[relative])
    assert candidates[root].category == "download cache"
    assert candidates[root].action == "move to Trash"
    assert candidates[root].recommended is True


def test_smart_ranking_prefers_large_safe_cache_over_old_personal_archive(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        storage_analyzer.shutil, "which",
        lambda name: "/usr/bin/gio" if name == "gio" else None,
    )
    cache = tmp_path / ".npm" / "_cacache" / "blob"
    cache.parent.mkdir(parents=True)
    with open(cache, "wb") as handle:
        handle.truncate(30 * 1024**2)
    archive = tmp_path / "Downloads" / "old.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"old")
    old = 100 * 86400
    os.utime(archive, (archive.stat().st_atime - old, archive.stat().st_mtime - old))

    inventory = analyze_home(
        str(tmp_path), [], duplicate_min_bytes=100 * 1024**2, max_seconds=5,
    )
    assert inventory.review_candidates[0].path == str(tmp_path / ".npm" / "_cacache")
    assert inventory.review_candidates[0].recommended is True


@pytest.mark.parametrize("relative", [
    ".npmrc",
    ".yarnrc.yml",
    ".cargo/config.toml",
    ".gradle/gradle.properties",
])
def test_ecosystem_configuration_is_never_a_cleanup_candidate(tmp_path, relative):
    configured = tmp_path / relative
    configured.parent.mkdir(parents=True, exist_ok=True)
    configured.write_text("important=true")

    inventory = analyze_home(str(tmp_path), [], duplicate_min_bytes=1)
    assert all(item.path != str(configured) for item in inventory.review_candidates)


def test_analyzer_creates_reversible_folder_review_action(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage_analyzer.shutil, "which",
        lambda name: "/usr/bin/gio" if name == "gio" else None,
    )
    modules = tmp_path / "Projects" / "web" / "node_modules"
    modules.mkdir(parents=True)
    with open(modules / "dependency.bin", "wb") as handle:
        handle.truncate(30 * 1024**2)

    inventory = analyze_home(str(tmp_path), [], max_seconds=5)
    candidate = next(item for item in inventory.review_candidates
                     if item.path == str(modules))
    assert candidate.category == "rebuildable folder"
    assert candidate.action == "move to Trash"
    assert "gio" in candidate.command and "trash" in candidate.command


def test_analyzer_discovers_sdk_packages_and_emulators(tmp_path):
    tools = tmp_path / "Android" / "Sdk" / "cmdline-tools" / "latest" / "bin"
    tools.mkdir(parents=True)
    for name in ("sdkmanager", "avdmanager"):
        tool = tools / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)

    image = (tmp_path / "Android" / "Sdk" / "system-images" / "android-35"
             / "google_apis" / "x86_64")
    image.mkdir(parents=True)
    (image / "system.img").write_bytes(b"image")
    avd = tmp_path / ".android" / "avd" / "Pixel.avd"
    avd.mkdir(parents=True)
    (avd / "userdata.img").write_bytes(b"userdata")

    inventory = analyze_home(str(tmp_path), [], duplicate_min_bytes=1000)
    sdk = next(item for item in inventory.review_candidates if item.category == "sdk")
    emulator = next(
        item for item in inventory.review_candidates if item.category == "emulator"
    )
    assert "sdkmanager" in sdk.command
    assert "system-images;android-35;google_apis;x86_64" in sdk.command
    assert "avdmanager" in emulator.command
    assert "Pixel" in emulator.command
