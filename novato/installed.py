# SPDX-License-Identifier: GPL-3.0-or-later
"""Queries about locally installed packages.

Before installing, Novato checks whether the package is already on the system
and *where it came from* (official repos vs the AUR), so it can offer an update
through the same source instead of blindly reinstalling. Updating an AUR
package with plain ``pacman`` would not rebuild it; it must go through the AUR
helper — knowing the origin matters.

Everything here is read-only and degrades gracefully: a missing binary or a
parse failure just means "not installed as far as we know".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .searcher import _run

# Origin labels for InstalledInfo.origin.
ORIGIN_OFFICIAL = "official"
ORIGIN_AUR = "aur"


@dataclass(frozen=True)
class InstalledInfo:
    """An installed package: its version and which source owns it."""

    name: str
    version: str
    origin: str  # ORIGIN_OFFICIAL or ORIGIN_AUR


def _parse_name_version_lines(out: str) -> dict[str, str]:
    """Parse ``name version`` lines (one package per line) into a dict."""
    versions: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            versions[parts[0]] = parts[1]
    return versions


def installed_versions(package_manager: str) -> dict[str, str]:
    """Return ``{package_name: version}`` for everything installed locally.

    One subprocess call per package manager, so it's cheap enough to run once
    per query. Unknown managers (or errors) return an empty dict.
    """
    if package_manager == "pacman":
        rc, out, _ = _run(["pacman", "-Q"])
    elif package_manager == "apt":
        rc, out, _ = _run(["dpkg-query", "-W", "-f", "${Package} ${Version}\n"])
    elif package_manager in ("dnf", "zypper"):
        rc, out, _ = _run(["rpm", "-qa", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\n"])
    else:
        return {}
    if rc != 0 or not out:
        return {}
    return _parse_name_version_lines(out)


def foreign_packages() -> set[str]:
    """Return the set of pacman "foreign" packages (AUR / manually built).

    ``pacman -Qm`` lists packages not found in any sync repo — on a typical
    Arch system that means AUR packages. Empty set on non-pacman systems.
    """
    rc, out, _ = _run(["pacman", "-Qm"])
    if rc != 0 or not out:
        return set()
    return {line.split()[0] for line in out.splitlines() if line.split()}


def get_info(package: str, package_manager: str) -> Optional[InstalledInfo]:
    """Return :class:`InstalledInfo` for ``package``, or None if not installed."""
    versions = installed_versions(package_manager)
    version = versions.get(package)
    if version is None:
        return None
    origin = ORIGIN_OFFICIAL
    if package_manager == "pacman" and package in foreign_packages():
        origin = ORIGIN_AUR
    return InstalledInfo(name=package, version=version, origin=origin)
