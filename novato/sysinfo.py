# SPDX-License-Identifier: GPL-3.0-or-later
"""System inspection helpers for ``/disk`` and ``/process``.

Two of the most common beginner panics — *"my disk is full"* and *"something is
stuck / using a port"* — have no GUI to fall back on. These helpers gather the
relevant facts (free space, biggest folders, what's holding a port) with plain,
read-only commands and return structured data the presenter can render calmly.

The functions take an injectable ``run`` callable so the parsing logic is unit-
testable without touching the real system. Nothing here executes a state-
changing command; killing a process is done by the caller through the normal
safety + confirmation gate.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

# A command runner returns the command's stdout (stripped), or "" on any error.
Runner = Callable[[str], str]


def _default_run(command: str) -> str:
    """Run a read-only command and capture stdout; return "" on any failure."""
    try:
        proc = subprocess.run(
            shlex.split(command),
            capture_output=True, text=True, timeout=15, check=False,
        )
        return proc.stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


@dataclass(frozen=True)
class DiskMount:
    """One row of ``df -h`` — a mounted filesystem and its usage."""

    filesystem: str
    size: str
    used: str
    avail: str
    use_percent: int
    mounted_on: str


@dataclass(frozen=True)
class DirSize:
    """A folder and its human-readable size (from ``du -sh``)."""

    size: str
    path: str


@dataclass(frozen=True)
class ProcInfo:
    """A running process, as much as we could learn about it."""

    pid: int
    name: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------

def disk_mounts(run: Runner = _default_run) -> list[DiskMount]:
    """Parse ``df -h`` into real, on-disk mounts (skips pseudo filesystems)."""
    out = run("df -h")
    mounts: list[DiskMount] = []
    for line in out.splitlines()[1:]:  # skip the header row
        cols = line.split()
        if len(cols) < 6:
            continue
        fs, size, used, avail, pct, mount = cols[0], cols[1], cols[2], cols[3], cols[4], cols[5]
        # Skip kernel/pseudo filesystems that only confuse a beginner.
        if fs in ("dev", "tmpfs", "devtmpfs", "efivarfs", "overlay") or fs.startswith("/dev/loop"):
            continue
        if mount.startswith(("/dev", "/sys", "/proc", "/run")):
            continue
        try:
            use_percent = int(pct.rstrip("%"))
        except ValueError:
            continue
        mounts.append(DiskMount(fs, size, used, avail, use_percent, mount))
    return mounts


def largest_dirs(
    path: str = "~", *, limit: int = 8, run: Runner = _default_run
) -> list[DirSize]:
    """Return the biggest immediate sub-folders of ``path``, largest first.

    Uses ``du`` on the directory's direct children only (``--max-depth=1``) so a
    huge home folder doesn't take forever. Best-effort: returns [] if du can't
    read the tree.
    """
    # -x stays on one filesystem; 2>/dev/null is added by the caller's shell-free
    # runner via stderr suppression below.
    out = run(f"du -h --max-depth=1 {path}")
    rows: list[DirSize] = []
    for line in out.splitlines():
        parts = line.split("\t") if "\t" in line else line.split(None, 1)
        if len(parts) != 2:
            continue
        size, p = parts[0].strip(), parts[1].strip()
        if p in (path, path.rstrip("/")):
            continue  # skip the grand total line for the dir itself
        rows.append(DirSize(size, p))
    rows.sort(key=lambda d: _size_to_bytes(d.size), reverse=True)
    return rows[:limit]


def _size_to_bytes(human: str) -> float:
    """Convert a ``du -h`` size like '2.4G' or '512K' to a sortable byte count."""
    human = human.strip()
    if not human:
        return 0.0
    units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    unit = human[-1].upper()
    if unit in units:
        try:
            return float(human[:-1]) * units[unit]
        except ValueError:
            return 0.0
    try:
        return float(human)
    except ValueError:
        return 0.0


def has_ncdu() -> bool:
    """True if the friendlier interactive disk analyser ``ncdu`` is installed."""
    return shutil.which("ncdu") is not None


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

def processes_on_port(port: int, run: Runner = _default_run) -> list[ProcInfo]:
    """Find which processes are holding a TCP port, best-effort across tools.

    Tries ``lsof`` first (clearest output), then falls back to ``ss`` and
    ``fuser`` so it still works on minimal systems. Returns an empty list if
    nothing is found or no tool is available.
    """
    if shutil.which("lsof"):
        out = run(f"lsof -i :{port} -sTCP:LISTEN -P -n")
        procs = _parse_lsof(out)
        if procs:
            return procs
    if shutil.which("ss"):
        out = run(f"ss -ltnp sport = :{port}")
        procs = _parse_ss(out)
        if procs:
            return procs
    if shutil.which("fuser"):
        out = run(f"fuser {port}/tcp")
        return [ProcInfo(pid=int(p), name="") for p in out.split() if p.isdigit()]
    return []


def _parse_lsof(out: str) -> list[ProcInfo]:
    """Parse ``lsof -i`` rows: COMMAND PID USER ... into ProcInfo (deduped)."""
    seen: dict[int, ProcInfo] = {}
    for line in out.splitlines()[1:]:  # skip header
        cols = line.split()
        if len(cols) < 2 or not cols[1].isdigit():
            continue
        pid = int(cols[1])
        seen.setdefault(pid, ProcInfo(pid=pid, name=cols[0]))
    return list(seen.values())


def _parse_ss(out: str) -> list[ProcInfo]:
    """Pull ``pid=NNN`` and the program name out of ``ss -ltnp`` output."""
    import re

    procs: dict[int, ProcInfo] = {}
    for match in re.finditer(r'users:\(\("([^"]+)",pid=(\d+)', out):
        name, pid = match.group(1), int(match.group(2))
        procs.setdefault(pid, ProcInfo(pid=pid, name=name))
    return list(procs.values())


def top_processes(
    *, limit: int = 10, sort_by: str = "mem", run: Runner = _default_run
) -> list[ProcInfo]:
    """Return the heaviest processes by memory (default) or CPU."""
    key = "%mem" if sort_by == "mem" else "%cpu"
    out = run(f"ps -eo pid=,comm=,{key.lstrip('%')}= --sort=-{key}")
    procs: list[ProcInfo] = []
    for line in out.splitlines():
        cols = line.split(None, 2)
        if len(cols) < 2 or not cols[0].isdigit():
            continue
        pid = int(cols[0])
        name = cols[1]
        detail = f"{key} {cols[2].strip()}" if len(cols) > 2 else ""
        procs.append(ProcInfo(pid=pid, name=name, detail=detail))
        if len(procs) >= limit:
            break
    return procs


def extract_port(query: str) -> Optional[int]:
    """Pull a port number out of a free-text query, e.g. 'using port 8080'."""
    import re

    match = re.search(r"\b(\d{2,5})\b", query)
    if not match:
        return None
    port = int(match.group(1))
    return port if 1 <= port <= 65535 else None
