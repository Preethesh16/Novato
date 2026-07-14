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


def test_paccache_preview_replaces_misleading_total_cache_estimate():
    def run(command: str) -> str:
        if command == "paccache -d -u -k 0":
            return "finished dry run: 4 candidates (disk space saved: 512 MiB)\n"
        if "/var/cache/pacman/pkg" in command:
            return f"{2 * 1024**3}\t/var/cache/pacman/pkg\n"
        return ""

    items = storage.cleanup_items(
        "pacman", "/home/u", run=run,
        available=lambda name: f"/usr/bin/{name}" if name == "paccache" else None,
    )
    package = next(item for item in items if item.key == "packages")
    assert package.estimated_bytes == 512 * 1024**2
    assert package.command == "sudo paccache -r -u -k 0"


def test_paccache_with_no_candidates_offers_no_package_cleanup():
    def run(command: str) -> str:
        if "/var/cache/pacman/pkg" in command:
            return f"{2 * 1024**3}\t/var/cache/pacman/pkg\n"
        return "==> no candidate packages found for pruning\n"

    items = storage.cleanup_items(
        "pacman", "/home/u", run=run,
        available=lambda name: "/usr/bin/paccache" if name == "paccache" else None,
    )
    assert all(item.key != "packages" for item in items)


def test_yay_build_cache_is_a_separate_arch_cleanup():
    gib = 1024**3

    def run(command: str) -> str:
        if command == "yay -Pg":
            return '{"buildDir":"/home/u/.cache/yay"}'
        if "/home/u/.cache/yay" in command:
            return f"{2 * gib}\t/home/u/.cache/yay\n"
        return ""

    items = storage.cleanup_items(
        "pacman", "/home/u", aur_helper="yay", run=run,
        available=lambda name: None,
    )
    aur = next(item for item in items if item.key == "aur-builds")
    assert aur.estimated_bytes == 2 * gib
    assert aur.command == "yay -Sc --aur"


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


def test_paccache_size_parser():
    assert storage._paccache_saved_bytes(
        "finished dry run (disk space saved: 1.5 GiB)"
    ) == int(1.5 * 1024**3)
    assert storage._paccache_saved_bytes("no candidates") == 0
