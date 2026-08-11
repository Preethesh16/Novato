# SPDX-License-Identifier: GPL-3.0-or-later
"""Compact local memory containing verified outcomes, never transcripts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from .agent_types import MemoryFact
from .config import config_dir, ensure_config_dir

MEMORY_FILENAME = "agent-memory.jsonl"


def memory_path() -> Path:
    return config_dir() / MEMORY_FILENAME


class MemoryStore:
    def load(self) -> list[MemoryFact]:
        facts: list[MemoryFact] = []
        try:
            lines = memory_path().read_text(encoding="utf-8").splitlines()
        except OSError:
            return facts
        for line in lines:
            try:
                raw = json.loads(line)
                facts.append(MemoryFact(**raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return facts

    def append(self, fact: MemoryFact) -> None:
        ensure_config_dir()
        path = memory_path()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(fact), ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)

    def forget(self, fact_id: str) -> int:
        current = self.load()
        kept = [] if fact_id == "all" else [fact for fact in current if fact.id != fact_id]
        removed = len(current) - len(kept)
        if removed:
            ensure_config_dir()
            path = memory_path()
            with open(path, "w", encoding="utf-8") as handle:
                for fact in kept:
                    handle.write(json.dumps(asdict(fact), ensure_ascii=False) + "\n")
            os.chmod(path, 0o600)
        return removed

