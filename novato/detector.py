"""System detection — distro, package manager, and shell.

Novato is distro-agnostic by design: nothing here is hardcoded to a single
distribution. We read ``/etc/os-release`` (via the ``distro`` library when
available, with a pure-stdlib fallback) and map the detected distribution to
the correct package-manager commands.

The detection result is a plain :class:`SystemInfo` dataclass so it can be
serialised, logged, and tested without touching the real system.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Distro -> package manager mapping.
#
# Keys are the lowercase ``ID`` (or ``ID_LIKE`` token) from /etc/os-release.
# ``install`` and ``search`` are never run with auto-confirm flags; the safety
# layer guarantees a human always confirms before execution.
# ---------------------------------------------------------------------------
DISTRO_PM_MAP: dict[str, dict] = {
    "arch":        {"pm": "pacman", "install": "sudo pacman -S",      "search": "pacman -Ss",       "aur": True},
    "manjaro":     {"pm": "pacman", "install": "sudo pacman -S",      "search": "pacman -Ss",       "aur": True},
    "endeavouros": {"pm": "pacman", "install": "sudo pacman -S",      "search": "pacman -Ss",       "aur": True},
    "garuda":      {"pm": "pacman", "install": "sudo pacman -S",      "search": "pacman -Ss",       "aur": True},
    "artix":       {"pm": "pacman", "install": "sudo pacman -S",      "search": "pacman -Ss",       "aur": True},
    "ubuntu":      {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "debian":      {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "linuxmint":   {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "pop":         {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "elementary":  {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "zorin":       {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "kali":        {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "raspbian":    {"pm": "apt",    "install": "sudo apt install",    "search": "apt-cache search", "aur": False},
    "fedora":      {"pm": "dnf",    "install": "sudo dnf install",    "search": "dnf search",       "aur": False},
    "rhel":        {"pm": "dnf",    "install": "sudo dnf install",    "search": "dnf search",       "aur": False},
    "centos":      {"pm": "dnf",    "install": "sudo dnf install",    "search": "dnf search",       "aur": False},
    "rocky":       {"pm": "dnf",    "install": "sudo dnf install",    "search": "dnf search",       "aur": False},
    "almalinux":   {"pm": "dnf",    "install": "sudo dnf install",    "search": "dnf search",       "aur": False},
    "opensuse":    {"pm": "zypper", "install": "sudo zypper install", "search": "zypper search",    "aur": False},
    "opensuse-leap":      {"pm": "zypper", "install": "sudo zypper install", "search": "zypper search", "aur": False},
    "opensuse-tumbleweed":{"pm": "zypper", "install": "sudo zypper install", "search": "zypper search", "aur": False},
    "sles":        {"pm": "zypper", "install": "sudo zypper install", "search": "zypper search",    "aur": False},
}

# Order matters: when a distro is unknown we fall back through its ID_LIKE
# tokens in this preference order.
_ID_LIKE_PRIORITY = ("arch", "debian", "ubuntu", "fedora", "rhel", "suse")

# Map a generic ID_LIKE family token to a representative key in DISTRO_PM_MAP.
_FAMILY_REPRESENTATIVE = {
    "arch": "arch",
    "debian": "debian",
    "ubuntu": "ubuntu",
    "fedora": "fedora",
    "rhel": "fedora",
    "suse": "opensuse",
}

# AUR helper preference order. Only consulted on pacman-based systems.
_AUR_HELPERS = ("yay", "paru", "pamac", "trizen", "pikaur")


@dataclass(frozen=True)
class SystemInfo:
    """Immutable snapshot of the host system relevant to Novato."""

    distro_id: str
    distro_name: str
    distro_version: str
    package_manager: str
    install_cmd: str
    search_cmd: str
    supports_aur: bool
    aur_helper: Optional[str]
    shell: str
    supported: bool = True
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Return a JSON-serialisable representation (for /status and logs)."""
        return {
            "distro_id": self.distro_id,
            "distro_name": self.distro_name,
            "distro_version": self.distro_version,
            "package_manager": self.package_manager,
            "install_cmd": self.install_cmd,
            "search_cmd": self.search_cmd,
            "supports_aur": self.supports_aur,
            "aur_helper": self.aur_helper,
            "shell": self.shell,
            "supported": self.supported,
        }


def _read_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    """Parse an os-release file into a dict without external dependencies.

    Returns an empty dict if the file is missing (e.g. non-Linux, containers).
    """
    data: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                # os-release values may be quoted; strip a single layer.
                value = value.strip().strip('"').strip("'")
                data[key.strip()] = value
    except OSError:
        return {}
    return data


def detect_distro_id(os_release: Optional[dict[str, str]] = None) -> tuple[str, str, str]:
    """Return ``(distro_id, pretty_name, version)``.

    Prefers the ``distro`` library when installed; otherwise parses
    ``/etc/os-release`` directly so detection never hard-fails.
    """
    if os_release is None:
        try:
            import distro as _distro  # type: ignore

            did = (_distro.id() or "").lower()
            name = _distro.name(pretty=True) or did or "Unknown"
            version = _distro.version(pretty=False) or ""
            if did:
                return did, name, version
        except Exception:
            pass  # Fall through to manual parsing.
        os_release = _read_os_release()

    did = (os_release.get("ID", "") or "").lower()
    name = os_release.get("PRETTY_NAME") or os_release.get("NAME") or did or "Unknown"
    version = os_release.get("VERSION_ID", "") or ""
    return did, name, version


def _resolve_pm_entry(distro_id: str, os_release: dict[str, str]) -> tuple[Optional[dict], str]:
    """Resolve a package-manager entry for ``distro_id``.

    Falls back through ``ID_LIKE`` family tokens for unknown derivatives so a
    brand-new Ubuntu remix still works. Returns ``(entry_or_None, resolved_id)``.
    """
    if distro_id in DISTRO_PM_MAP:
        return DISTRO_PM_MAP[distro_id], distro_id

    id_like = (os_release.get("ID_LIKE", "") or "").lower().split()
    for family in _ID_LIKE_PRIORITY:
        if family in id_like:
            rep = _FAMILY_REPRESENTATIVE.get(family)
            if rep and rep in DISTRO_PM_MAP:
                return DISTRO_PM_MAP[rep], rep
    return None, distro_id


def detect_shell(environ: Optional[dict] = None) -> str:
    """Return the user's shell name (e.g. ``zsh``, ``bash``).

    Uses ``$SHELL`` which reflects the login shell. Returns ``"unknown"`` when
    it cannot be determined.
    """
    environ = environ if environ is not None else os.environ
    shell_path = environ.get("SHELL", "")
    if shell_path:
        return os.path.basename(shell_path)
    return "unknown"


def detect_aur_helper() -> Optional[str]:
    """Return the first installed AUR helper, or ``None`` if none are present."""
    for helper in _AUR_HELPERS:
        if shutil.which(helper):
            return helper
    return None


def detect_system(os_release_path: str = "/etc/os-release") -> SystemInfo:
    """Detect the full system profile Novato needs to operate.

    This is the single entry point the rest of Novato should call. It is safe
    to run on unsupported systems — ``supported`` will be ``False`` and the
    package-manager fields fall back to sensible placeholders.
    """
    os_release = _read_os_release(os_release_path)
    distro_id, distro_name, version = detect_distro_id(os_release or None)
    entry, resolved_id = _resolve_pm_entry(distro_id, os_release)
    shell = detect_shell()

    if entry is None:
        return SystemInfo(
            distro_id=distro_id or "unknown",
            distro_name=distro_name,
            distro_version=version,
            package_manager="unknown",
            install_cmd="",
            search_cmd="",
            supports_aur=False,
            aur_helper=None,
            shell=shell,
            supported=False,
        )

    supports_aur = bool(entry["aur"])
    aur_helper = detect_aur_helper() if supports_aur else None

    return SystemInfo(
        distro_id=distro_id or resolved_id,
        distro_name=distro_name,
        distro_version=version,
        package_manager=entry["pm"],
        install_cmd=entry["install"],
        search_cmd=entry["search"],
        supports_aur=supports_aur,
        aur_helper=aur_helper,
        shell=shell,
        supported=True,
        extra={"resolved_via": resolved_id if resolved_id != distro_id else ""},
    )
