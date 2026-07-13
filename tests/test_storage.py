"""Tests for the smart, distro-aware storage workflow."""

from __future__ import annotations

from collections import namedtuple

from novato import storage


def _sizes(values):
    def run(command: str) -> str:
        for path, size in values.items():
            if path in command:
                return f"{size}\t{path}\n"
        return ""
    return run


def test_cleanup_commands_are_distro_aware():
    paths = {
        "/var/cache/pacman/pkg": 1000,
        "/var/cache/apt/archives": 2000,
        "/var/cache/dnf": 3000,
    }
    expected = {
        "pacman": "sudo pacman -Sc",
        "apt": "sudo apt clean",
        "dnf": "sudo dnf clean packages",
    }
    for manager, command in expected.items():
        items = storage.cleanup_items(
            manager, "/home/u", run=_sizes(paths), available=lambda name: None,
        )
        assert items[0].command == command
        assert "-y" not in items[0].command


def test_cleanup_detects_trash_and_keeps_journal_bounded():
    mib = 1024 * 1024
    run = _sizes({
        "/home/u/.local/share/Trash": 25 * mib,
        "/var/log/journal": 350 * mib,
    })
    items = storage.cleanup_items(
        "unknown", "/home/u", run=run, available=lambda name: f"/usr/bin/{name}",
    )
    commands = {item.key: item.command for item in items}
    assert commands["trash"] == "gio trash --empty"
    assert commands["journal"] == "sudo journalctl --vacuum-size=200M"


def test_deep_scan_reports_personal_cache_but_never_creates_delete_command(monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        "novato.sysinfo.largest_dirs",
        lambda path, **kwargs: [storage.DirSize("2G", f"{path}/browser")],
    )
    scan = storage.deep_scan(
        "unknown", "/home/u", run=lambda command: "",
        disk_usage=lambda path: Usage(10_000, 7_000, 3_000),
        available=lambda name: None,
    )
    assert scan.free_bytes == 3_000
    assert scan.cache_dirs[0].path == "/home/u/.cache/browser"
    assert not scan.cleanup


def test_format_bytes():
    assert storage.format_bytes(0) == "0 B"
    assert storage.format_bytes(1024**3) == "1.0 GB"


def test_capacity_scan_is_fast_and_read_only():
    Usage = namedtuple("Usage", "total used free")
    scan = storage.capacity_scan(
        "/home/u", disk_usage=lambda path: Usage(100, 60, 40),
    )
    assert (scan.total_bytes, scan.used_bytes, scan.free_bytes) == (100, 60, 40)
    assert scan.cleanup == []
