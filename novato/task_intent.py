# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured intents for actions Novato performs itself (not packages)."""

from __future__ import annotations

from dataclasses import dataclass

STORAGE_CHECK = "storage_check"
STORAGE_CLEAN = "storage_clean"
TASK_ACTIONS = frozenset({STORAGE_CHECK, STORAGE_CLEAN})


@dataclass(frozen=True)
class TaskIntent:
    """A natural-language request classified as a built-in Novato action."""

    query: str
    action: str = ""
    confidence: float = 0.0
    source: str = "basic"

    @property
    def found(self) -> bool:
        return self.action in TASK_ACTIONS
