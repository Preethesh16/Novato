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
        "/var/cache/zypp/packages": 4000,
    }
    expected = {
        "pacman": "sudo pacman -Sc",
        "apt": "sudo apt clean",
        "dnf": "sudo dnf clean packages",
        "zypper": "sudo zypper clean --all",
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


def test_deep_scan_refreshes_capacity_after_analysis(tmp_path, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    analysis_finished = False
    expected_dirs = [storage.DirSize("2G", str(tmp_path / "cache"))]

    monkeypatch.setattr(
        "novato.sysinfo.largest_dirs",
        lambda path, **kwargs: expected_dirs if path == str(tmp_path) else [],
    )

    def analyze_home(home, rows):
        nonlocal analysis_finished
        assert home == str(tmp_path)
        assert rows == expected_dirs
        analysis_finished = True
        return storage.Inventory()

    def changing_disk_usage(path):
        if analysis_finished:
            return Usage(100, 60, 40)
        return Usage(100, 90, 10)

    monkeypatch.setattr(storage, "analyze_home", analyze_home)

    scan = storage.deep_scan(
        "unknown", str(tmp_path), run=lambda command: "",
        disk_usage=changing_disk_usage, available=lambda name: None,
    )

    assert scan.large_dirs == expected_dirs
    assert (scan.total_bytes, scan.used_bytes, scan.free_bytes) == (100, 60, 40)
    assert scan.filesystems
    assert all(
        (item.total_bytes, item.used_bytes, item.free_bytes) == (100, 60, 40)
        for item in scan.filesystems
    )


def test_format_bytes():
    assert storage.format_bytes(0) == "0 B"
    assert storage.format_bytes(1024**3) == "1.0 GB"


def test_directory_bytes_requests_allocated_not_apparent_size():
    commands = []

    def run(command):
        commands.append(command)
        return "4096\t/some/cache\n"

    assert storage.directory_bytes("/some/cache", run=run) == 4096
    assert commands == ["du -s -B1 -- /some/cache"]


def test_capacity_scan_is_fast_and_read_only():
    Usage = namedtuple("Usage", "total used free")
    scan = storage.capacity_scan(
        "/home/u", disk_usage=lambda path: Usage(100, 60, 40),
    )
    assert (scan.total_bytes, scan.used_bytes, scan.free_bytes) == (100, 60, 40)
    assert scan.cleanup == []


def test_settle_capacity_uses_latest_sample(tmp_path, monkeypatch):
    clock = [0.0]

    def sample(*args, **kwargs):
        free = 40 if clock[0] >= 2.5 else 10
        return storage.StorageScan(100, 100 - free, free)

    monkeypatch.setattr(storage, "capacity_scan", sample)
    initial = storage.StorageScan(100, 95, 5)

    def advance(seconds):
        clock[0] += seconds

    settled = storage.settle_capacity(
        initial, str(tmp_path), interval=0.5, min_wait=3.0, stable_for=1.0,
        max_wait=10.0, sleep=advance, monotonic=lambda: clock[0],
        trash_pending=lambda path: False,
    )

    assert (settled.used_bytes, settled.free_bytes) == (60, 40)
    assert clock[0] >= 3.5


def test_settle_capacity_waits_while_trash_expunging(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(
        storage, "capacity_scan", lambda *a, **k: storage.StorageScan(100, 50, 50),
    )

    settled = storage.settle_capacity(
        storage.StorageScan(100, 90, 10), str(tmp_path), interval=0.5,
        min_wait=0.0, stable_for=0.5, max_wait=10.0,
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        monotonic=lambda: clock[0],
        trash_pending=lambda path: clock[0] < 4.0,
    )

    assert settled.free_bytes == 50
    assert clock[0] >= 4.0


def test_paccache_size_parser():
    assert storage._paccache_saved_bytes(
        "finished dry run (disk space saved: 1.5 GiB)"
    ) == int(1.5 * 1024**3)
    assert storage._paccache_saved_bytes("no candidates") == 0
