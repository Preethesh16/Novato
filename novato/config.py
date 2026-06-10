# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration storage for Novato.

Config lives in ``~/.novato/config.json``. It is intentionally small and
human-readable so users can inspect or edit it by hand. The API here is a thin,
well-typed wrapper around that file with safe defaults and atomic writes.

No secrets beyond the Groq API key are stored. The key is kept in the config
file with ``0600`` permissions; see :func:`save_config`.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Valid AI modes, in rough order of capability. ``basic`` always works.
VALID_MODES = ("basic", "offline", "online", "both")

DEFAULT_CONFIG_DIR = Path.home() / ".novato"
CONFIG_FILENAME = "config.json"


@dataclass
class Config:
    """Typed view of Novato's persisted settings."""

    mode: str = "basic"
    explain: bool = False
    mistake: bool = False
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llamafile_path: str = ""
    llamafile_model: str = ""
    setup_complete: bool = False
    version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            self.mode = "basic"

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key.strip())

    @property
    def has_llamafile(self) -> bool:
        return bool(self.llamafile_path.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def config_dir() -> Path:
    """Return the Novato config directory, honouring ``$NOVATO_HOME``."""
    override = os.environ.get("NOVATO_HOME")
    return Path(override) if override else DEFAULT_CONFIG_DIR


def config_path() -> Path:
    """Return the absolute path to ``config.json``."""
    return config_dir() / CONFIG_FILENAME


def ensure_config_dir() -> Path:
    """Create the config directory (mode 0700) if needed and return it."""
    d = config_dir()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Tighten permissions even if it already existed with looser ones.
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def _coerce(raw: dict[str, Any]) -> Config:
    """Build a Config from raw JSON, ignoring unknown keys gracefully."""
    known = {f for f in Config.__dataclass_fields__ if f != "extra"}  # type: ignore[attr-defined]
    kwargs = {k: v for k, v in raw.items() if k in known}
    extra = {k: v for k, v in raw.items() if k not in known}
    cfg = Config(**kwargs)
    if extra:
        cfg.extra.update(extra)
    return cfg


def load_config() -> Config:
    """Load config from disk, returning defaults if it is missing or invalid.

    A corrupt config file never crashes Novato — we fall back to defaults so
    the tool keeps working in basic mode.
    """
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return Config()
        return _coerce(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return Config()


def save_config(cfg: Config) -> Path:
    """Atomically persist config to disk with restrictive permissions.

    Writes to a temp file in the same directory then ``os.replace`` so a crash
    mid-write never leaves a truncated config. The file is chmod ``0600`` since
    it may contain the Groq API key.
    """
    ensure_config_dir()
    path = config_path()
    data = json.dumps(cfg.to_dict(), indent=2, sort_keys=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except OSError:
        # Best-effort cleanup; re-raise so callers can surface the failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def update_config(**changes: Any) -> Config:
    """Load, apply ``changes``, save, and return the updated config.

    Convenience for the common read-modify-write cycle used by slash commands.
    Unknown keys are rejected with ``KeyError`` to catch typos early.
    """
    cfg = load_config()
    valid = set(Config.__dataclass_fields__)  # type: ignore[attr-defined]
    for key, value in changes.items():
        if key not in valid:
            raise KeyError(f"Unknown config key: {key!r}")
        setattr(cfg, key, value)
    cfg.__post_init__()  # Re-validate (e.g. mode).
    save_config(cfg)
    return cfg
