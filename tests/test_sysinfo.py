"""Tests for the disk/process inspection helpers."""

from __future__ import annotations

from novato import sysinfo

_DF = """Filesystem      Size  Used Avail Use% Mounted on
dev             7.8G     0  7.8G   0% /dev
/dev/nvme0n1p2  450G  380G   47G  90% /
tmpfs           7.9G  1.2M  7.9G   1% /run
/dev/nvme0n1p1  1.1G  312M  788M  29% /boot
"""

_DU = "2.4G\t/home/u/Videos\n512M\t/home/u/Downloads\n8.0K\t/home/u/.cache\n3.0G\t/home/u\n"

_LSOF = """COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
node    12345   u   23u  IPv4  98765      0t0  TCP *:8080 (LISTEN)
node    12345   u   24u  IPv4  98766      0t0  TCP *:8080 (LISTEN)
"""


def test_disk_mounts_skips_pseudo_filesystems():
    mounts = sysinfo.disk_mounts(run=lambda c: _DF)
    points = [m.mounted_on for m in mounts]
    assert "/" in points and "/boot" in points
    assert "/dev" not in points and "/run" not in points


def test_disk_mounts_parses_percentage():
    mounts = sysinfo.disk_mounts(run=lambda c: _DF)
    root = next(m for m in mounts if m.mounted_on == "/")
    assert root.use_percent == 90
    assert root.avail == "47G"


def test_largest_dirs_sorted_descending_and_excludes_self():
    dirs = sysinfo.largest_dirs("/home/u", run=lambda c: _DU)
    paths = [d.path for d in dirs]
    assert "/home/u" not in paths  # the grand-total line is dropped
    assert paths[0] == "/home/u/Videos"  # 2.4G is the biggest child


def test_size_to_bytes_orders_units():
    assert sysinfo._size_to_bytes("1G") > sysinfo._size_to_bytes("900M")
    assert sysinfo._size_to_bytes("2K") > sysinfo._size_to_bytes("500B")


def test_parse_lsof_dedupes_by_pid():
    procs = sysinfo._parse_lsof(_LSOF)
    assert len(procs) == 1
    assert procs[0].pid == 12345
    assert procs[0].name == "node"


def test_parse_ss_extracts_pid_and_name():
    ss = 'LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* users:(("gunicorn",pid=999,fd=7))'
    procs = sysinfo._parse_ss(ss)
    assert procs[0].pid == 999
    assert procs[0].name == "gunicorn"


def test_extract_port():
    assert sysinfo.extract_port("what is using port 8080") == 8080
    assert sysinfo.extract_port("free up port 22 please") == 22
    assert sysinfo.extract_port("no number here") is None
    assert sysinfo.extract_port("port 99999") is None  # out of range


def test_top_processes_with_real_ps_returns_results():
    """Regression: the ps format spec must be valid so real ps returns rows.

    Uses the real `ps` (no mock) because the original bug was a malformed
    column specifier ('mem=' instead of '%mem=') that only fails against the
    actual binary — a mocked runner would hide it.
    """
    procs = sysinfo.top_processes(limit=5)
    assert procs, "top_processes returned nothing — ps spec is likely malformed"
    assert all(p.pid > 0 for p in procs)
    assert all(p.name for p in procs)


def test_top_processes_builds_valid_ps_spec():
    """The generated ps command must use '%mem'/'%cpu', never a bare 'mem'/'cpu'."""
    seen = {}

    def fake_run(cmd: str) -> str:
        seen["cmd"] = cmd
        return "1234 bash 1.2\n"

    sysinfo.top_processes(run=fake_run, sort_by="mem")
    assert "%mem=" in seen["cmd"]
    assert ",mem=" not in seen["cmd"]

    sysinfo.top_processes(run=fake_run, sort_by="cpu")
    assert "%cpu=" in seen["cmd"]
    assert ",cpu=" not in seen["cmd"]
