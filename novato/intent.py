# SPDX-License-Identifier: GPL-3.0-or-later
"""Natural-language intent front-end.

This module is the thin orchestration seam between a raw user query and the
package candidates we will search for. It delegates the actual language work to
a *backend* (Basic mode now; llamafile/Groq via the router in Phase 3) so the
rest of the pipeline never needs to know which AI tier answered.

The output is an :class:`IntentPlan` — the matched intent, an ordered list of
candidate package names, and metadata for the presenter's status badge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .backends.basic_backend import BasicBackend, IntentResult
from .task_intent import TaskIntent


@dataclass
class IntentPlan:
    """Resolved plan: what the user wants, expressed as package candidates."""

    query: str
    candidates: list[str] = field(default_factory=list)
    matched_intent: str = ""
    confidence: float = 0.0
    backend: str = "basic"

    @property
    def understood(self) -> bool:
        """True when we have at least one candidate to search for."""
        return bool(self.candidates)


class IntentResolver:
    """Resolve queries into :class:`IntentPlan` using a pluggable backend.

    ``backend`` only needs a ``resolve_intent(query) -> IntentResult`` method and
    a ``name`` attribute, so the Phase 3 router slots in unchanged.
    """

    def __init__(self, backend=None) -> None:
        self._backend = backend or BasicBackend()

    @property
    def backend_name(self) -> str:
        return getattr(self._backend, "name", "basic")

    def resolve(self, query: str) -> IntentPlan:
        """Turn a free-text query into an :class:`IntentPlan`."""
        query = query.strip()
        if not query:
            return IntentPlan(query="", backend=self.backend_name)

        result: IntentResult = self._backend.resolve_intent(query)
        return IntentPlan(
            query=query,
            candidates=list(result.candidates),
            matched_intent=result.matched_intent,
            confidence=result.score,
            backend=getattr(result, "source", self.backend_name),
        )

    def resolve_task(self, query: str) -> TaskIntent:
        """Classify a request for a built-in action through the active backend."""
        query = query.strip()
        if not query:
            return TaskIntent(query="", source=self.backend_name)
        classify = getattr(self._backend, "resolve_task", None)
        if classify is None:
            return TaskIntent(query=query, source=self.backend_name)
        return classify(query)
