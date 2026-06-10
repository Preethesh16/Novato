"""AI-mode management (`/switch`).

A thin, well-validated layer over the persisted ``mode`` setting. Keeping this
separate from :mod:`main` makes the mode rules (valid values, descriptions, the
recommended default) testable in isolation and reusable by the setup wizard.
"""

from __future__ import annotations

from . import config as _config

# Human-readable, beginner-facing description of each mode.
MODE_DESCRIPTIONS = {
    "basic":   "Rules only, no AI — instant, 100% private, always works.",
    "offline": "Local llamafile LLM — private, works without internet.",
    "online":  "Groq API — fastest inference anywhere, completely free.",
    "both":    "Groq online + llamafile fallback — best experience.",
}

RECOMMENDED_MODE = "both"


class ModeSwitchError(ValueError):
    """Raised when an invalid mode is requested."""


def valid_modes() -> tuple[str, ...]:
    return _config.VALID_MODES


def current_mode(cfg: _config.Config | None = None) -> str:
    cfg = cfg or _config.load_config()
    return cfg.mode


def describe(mode: str) -> str:
    return MODE_DESCRIPTIONS.get(mode, "")


def switch(mode: str) -> _config.Config:
    """Persist a new AI mode. Raises :class:`ModeSwitchError` if invalid."""
    mode = mode.strip().lower()
    if mode not in _config.VALID_MODES:
        raise ModeSwitchError(
            f"'{mode}' is not a valid mode. Choose one of: "
            + ", ".join(_config.VALID_MODES)
        )
    return _config.update_config(mode=mode)


def mode_menu() -> list[tuple[str, str]]:
    """Return ``(mode, description)`` pairs for presenting a switch menu."""
    return [(m, MODE_DESCRIPTIONS.get(m, "")) for m in _config.VALID_MODES]
