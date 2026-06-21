# SPDX-License-Identifier: GPL-3.0-or-later
"""Package repository search across distros.

Given a list of candidate package names (from the intent layer) or a free-text
query, :mod:`searcher` looks them up in the *real* repositories for the detected
distro and returns structured :class:`SearchResult` objects the ranker and
presenter can use.

Backends:

* **pacman** — ``pacman -Ss`` (official repos) via subprocess.
* **AUR**    — ``aur.archlinux.org/rpc/v5`` REST API via :mod:`requests`.
* **apt**    — ``apt-cache search`` via subprocess.
* **dnf**    — ``dnf search`` via subprocess.
* **zypper** — ``zypper search`` via subprocess.

Every search degrades gracefully: a missing binary, a network failure, or a
timeout yields an empty result list rather than an exception. Nothing here ever
executes an install — it only reads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Network/subprocess timeouts kept short so the UI never hangs.
_SUBPROCESS_TIMEOUT = 12  # seconds
_HTTP_TIMEOUT = 8         # seconds

AUR_RPC_URL = "https://aur.archlinux.org/rpc/v5"


@dataclass
class SearchResult:
    """A single package found in a repository."""

    name: str
    description: str = ""
    repo: str = ""           # e.g. "extra", "AUR", "official".
    version: str = ""
    source: str = ""         # which backend produced it: pacman/aur/apt/...
    popularity: float = 0.0  # AUR popularity or 0 when unknown.
    installed: bool = False
    extra: dict = field(default_factory=dict)

    def key(self) -> str:
        """Dedup key — package name is unique enough within a distro."""
        return self.name.lower()


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run a read-only command, returning ``(rc, stdout, stderr)``.

    Never raises: a missing binary or timeout returns a non-zero rc and empty
    output so callers can simply treat it as "no results".
    """
    if not shutil.which(cmd[0]):
        return 127, "", f"{cmd[0]}: not found"
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
            # Read-only query commands must never read the terminal's stdin —
            # otherwise a child run just before a y/N prompt can swallow the
            # user's piped answer and the confirmation silently sees EOF.
            stdin=subprocess.DEVNULL,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)


# ---------------------------------------------------------------------------
# pacman (Arch official repos)
# ---------------------------------------------------------------------------

def search_pacman(query: str) -> list[SearchResult]:
    """Search official Arch repos with ``pacman -Ss``.

    ``pacman -Ss`` output looks like::

        extra/vlc 3.0.20-4 [installed]
            A free and open source cross-platform multimedia player
    """
    rc, out, _ = _run(["pacman", "-Ss", query])
    if rc != 0 or not out:
        return []
    results: list[SearchResult] = []
    lines = out.splitlines()
    i = 0
    while i < len(lines):
        header = lines[i]
        if "/" not in header.split(" ")[0]:
            i += 1
            continue
        repo_name, _, rest = header.partition("/")
        parts = rest.split()
        name = parts[0] if parts else ""
        version = parts[1] if len(parts) > 1 else ""
        installed = "[installed" in header
        description = ""
        if i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
            description = lines[i + 1].strip()
            i += 1
        results.append(SearchResult(
            name=name, description=description, repo=repo_name,
            version=version, source="pacman", installed=installed,
        ))
        i += 1
    return results


# ---------------------------------------------------------------------------
# AUR (Arch User Repository) — REST API
# ---------------------------------------------------------------------------

def search_aur(query: str, *, opener=None) -> list[SearchResult]:
    """Search the AUR via its RPC v5 ``search`` endpoint.

    ``opener`` is injectable for testing (defaults to urllib). Network errors
    return an empty list.
    """
    url = f"{AUR_RPC_URL}/search/{urllib.parse.quote(query)}?by=name-desc"
    try:
        if opener is None:
            with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
        else:
            raw = opener(url)
    except Exception:
        return []
    return _parse_aur_json(raw)


def _parse_aur_json(raw: str) -> list[SearchResult]:
    """Parse an AUR RPC JSON response into SearchResults."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict) or data.get("type") == "error":
        return []
    results = []
    for item in data.get("results", []):
        results.append(SearchResult(
            name=item.get("Name", ""),
            description=item.get("Description") or "",
            repo="AUR",
            version=item.get("Version", ""),
            source="aur",
            popularity=float(item.get("Popularity", 0.0) or 0.0),
            extra={"votes": item.get("NumVotes", 0),
                   "maintainer": item.get("Maintainer") or ""},
        ))
    return results


# ---------------------------------------------------------------------------
# apt (Debian/Ubuntu)
# ---------------------------------------------------------------------------

def search_apt(query: str) -> list[SearchResult]:
    """Search apt's package cache with ``apt-cache search``.

    Output: ``package-name - short description`` per line.
    """
    rc, out, _ = _run(["apt-cache", "search", query])
    if rc != 0 or not out:
        return []
    results = []
    for line in out.splitlines():
        name, _, desc = line.partition(" - ")
        name = name.strip()
        if not name:
            continue
        results.append(SearchResult(
            name=name, description=desc.strip(), repo="apt", source="apt",
        ))
    return results


# ---------------------------------------------------------------------------
# dnf (Fedora/RHEL)
# ---------------------------------------------------------------------------

def search_dnf(query: str) -> list[SearchResult]:
    """Search with ``dnf search``.

    Output groups results with a ``Name : Summary`` shape; lines look like::

        vlc.x86_64 : The cross-platform open-source multimedia framework ...
    """
    rc, out, _ = _run(["dnf", "search", "-q", query])
    if rc != 0 or not out:
        return []
    results = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("=") or " : " not in line:
            continue
        name_part, _, desc = line.partition(" : ")
        name = name_part.split(".")[0].strip()  # strip .x86_64/.noarch arch.
        if not name:
            continue
        results.append(SearchResult(
            name=name, description=desc.strip(), repo="dnf", source="dnf",
        ))
    return results


# ---------------------------------------------------------------------------
# zypper (openSUSE)
# ---------------------------------------------------------------------------

def search_zypper(query: str) -> list[SearchResult]:
    """Search with ``zypper search`` (table output, ``|``-delimited)."""
    rc, out, _ = _run(["zypper", "--quiet", "search", query])
    if rc != 0 or not out:
        return []
    results = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        cols = [c.strip() for c in line.split("|")]
        # Skip header/separator rows.
        if len(cols) < 2 or cols[1].lower() in ("name", ""):
            continue
        name = cols[1]
        desc = cols[2] if len(cols) > 2 else ""
        results.append(SearchResult(
            name=name, description=desc, repo="zypper", source="zypper",
        ))
    return results


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_PM_DISPATCH = {
    "pacman": search_pacman,
    "apt": search_apt,
    "dnf": search_dnf,
    "zypper": search_zypper,
}


def _dedup(results: Iterable[SearchResult]) -> list[SearchResult]:
    """Remove duplicate packages, keeping the first (repo-preferred) entry."""
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        if r.key() in seen:
            continue
        seen.add(r.key())
        out.append(r)
    return out


def search(query: str, package_manager: str, *, include_aur: bool = False) -> list[SearchResult]:
    """Search the repositories appropriate for ``package_manager``.

    Official repos are searched first; the AUR (if ``include_aur``) is appended
    afterward so official packages naturally rank above AUR ones. Results are
    de-duplicated by package name.
    """
    backend = _PM_DISPATCH.get(package_manager)
    results: list[SearchResult] = []
    if backend is not None:
        results.extend(backend(query))
    if include_aur:
        results.extend(search_aur(query))
    return _dedup(results)


# Common packaging suffixes: "brave" is published on the AUR as "brave-bin",
# many apps ship as "<name>-git", etc. Used to recognise the real package when
# the AI suggests the bare app name.
_PKG_SUFFIXES = ("-bin", "-git", "-browser", "-desktop", "-appimage")


def _best_match(cand: str, hits: list[SearchResult]) -> Optional[SearchResult]:
    """Pick the hit that most plausibly *is* ``cand``.

    Preference order: exact name -> name with a known packaging suffix
    (``brave`` -> ``brave-bin``) -> most popular name-prefix match -> first hit.
    """
    if not hits:
        return None
    low = cand.lower()
    exact = next((h for h in hits if h.name.lower() == low), None)
    if exact is not None:
        return exact
    suffixed = {low + suf for suf in _PKG_SUFFIXES}
    for h in hits:
        if h.name.lower() in suffixed:
            return h
    prefixed = [h for h in hits if h.name.lower().startswith(low)]
    if prefixed:
        return max(prefixed, key=lambda h: (h.popularity, -len(h.name)))
    return hits[0]


def search_candidates(
    candidates: list[str],
    package_manager: str,
    *,
    include_aur: bool = False,
    query: Optional[str] = None,
) -> list[SearchResult]:
    """Resolve a list of candidate package names against the repos.

    For each candidate we run a targeted search and keep the most plausible
    match (see :func:`_best_match`). A hyphenated candidate that finds nothing
    is retried on its first word — AI tiers often say ``brave-browser`` while
    the real package is ``brave-bin``, which only a search for ``brave`` finds.
    Candidates that still don't resolve are dropped silently.
    """
    found: list[SearchResult] = []
    seen: set[str] = set()
    for cand in candidates:
        hits = search(cand, package_manager, include_aur=include_aur)
        if not hits and "-" in cand:
            stem = cand.split("-", 1)[0]
            if stem:
                cand = stem
                hits = search(stem, package_manager, include_aur=include_aur)
        chosen = _best_match(cand, hits)
        if chosen is None or chosen.key() in seen:
            continue
        seen.add(chosen.key())
        found.append(chosen)
    return found
