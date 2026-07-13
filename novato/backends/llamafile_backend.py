# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline AI backend — llamafile (Mozilla).

llamafile bundles an inference engine and a model into a single executable with
no daemon, so Novato can ship/offline-run a local LLM without the RAM overhead
of an always-on service. This backend shells out to that binary for one-shot
completions and reuses the same response-parsing helpers as the Groq backend.

Everything here is 100% local — nothing leaves the machine. If the binary is
missing or inference fails, methods return empty/``None`` so the router falls
through to Basic mode.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from .basic_backend import IntentResult
from .groq_backend import (
    _ERROR_SYSTEM_PROMPT,
    _INTENT_SYSTEM_PROMPT,
    _TASK_SYSTEM_PROMPT,
    _parse_json_object,
    _parse_package_list,
)
from ..task_intent import TASK_ACTIONS, TaskIntent

_TIMEOUT = 30  # seconds — local CPU inference is slower than Groq.
_MAX_CANDIDATES = 6

# Model selection + download now live in novato.downloader (the single source of
# truth for the offline model registry). Re-exported here for convenience.
from ..downloader import ModelSpec, select_model  # noqa: E402,F401


class LlamafileBackend:
    """Local llamafile-backed intent + error resolver."""

    name = "offline"

    def __init__(self, binary_path: str, *, runner=None) -> None:
        self._path = binary_path
        # ``runner`` lets tests inject a fake inference function
        # (prompt -> text) without a real binary.
        self._runner = runner

    @property
    def available(self) -> bool:
        if self._runner is not None:
            return True
        return bool(self._path) and os.path.isfile(self._path) and os.access(self._path, os.X_OK)

    # -- Inference plumbing -------------------------------------------------

    def _complete(self, system: str, user: str) -> Optional[str]:
        """Run one local completion, returning generated text or None."""
        prompt = f"{system}\n\nRequest: {user}\nAnswer:"
        if self._runner is not None:
            try:
                return self._runner(prompt)
            except Exception:
                return None
        if not self.available:
            return None
        # llamafile CLI one-shot: deterministic, silent, capped tokens.
        cmd = [
            self._path,
            "--cli",
            "--temp", "0.2",
            "-n", "256",
            "--silent-prompt",
            "-p", prompt,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_TIMEOUT, check=False
            )
            if proc.returncode != 0:
                return None
            return proc.stdout
        except (subprocess.TimeoutExpired, OSError):
            return None

    # -- Intent -------------------------------------------------------------

    def resolve_intent(self, query: str) -> IntentResult:
        text = self._complete(_INTENT_SYSTEM_PROMPT, query.strip())
        candidates = _parse_package_list(text) if text else []
        if not candidates:
            return IntentResult(query, source="offline")
        return IntentResult(
            query=query,
            matched_intent=query.strip().lower(),
            candidates=candidates[:_MAX_CANDIDATES],
            score=0.8,
            source="offline",
        )

    def resolve_task(self, query: str) -> TaskIntent:
        text = self._complete(_TASK_SYSTEM_PROMPT, query.strip())
        obj = _parse_json_object(text) if text else None
        if not obj:
            return TaskIntent(query, source=self.name)
        action = str(obj.get("action", "")).strip().lower()
        try:
            confidence = float(obj.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if action not in TASK_ACTIONS or confidence < 0.65:
            return TaskIntent(query, source=self.name)
        return TaskIntent(query, action, min(1.0, confidence), self.name)

    def describe(self, package: str) -> str:
        return ""

    # -- Error analysis -----------------------------------------------------

    def analyze_error(self, ctx) -> Optional["object"]:
        from .. import rules as _rules
        from .. import safety as _safety

        user = f"Command: {ctx.command}\nExit code: {ctx.exit_code}\nError:\n{ctx.stderr}"
        text = self._complete(_ERROR_SYSTEM_PROMPT, user)
        if not text:
            return None
        obj = _parse_json_object(text)
        if not obj or "title" not in obj:
            return None
        fix = (obj.get("fix") or "").strip()
        if fix and not _safety.validate(fix).allowed:
            fix = ""
        return _rules.Correction(
            title=str(obj.get("title", ""))[:200],
            reason=str(obj.get("reason", ""))[:400],
            fix=fix,
            confidence=0.8,
            rule_name="llamafile",
        )

    def build_command(self, system: str, user: str) -> list[str]:
        """Expose the CLI command (used in diagnostics/tests)."""
        prompt = f"{system}\n\nRequest: {user}\nAnswer:"
        return [self._path, "--cli", "--temp", "0.2", "-n", "256",
                "--silent-prompt", "-p", prompt]
