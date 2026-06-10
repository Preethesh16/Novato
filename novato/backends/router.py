"""Backend router — the fallback chain that makes Novato unbreakable.

The router assembles an ordered list of backends from the user's chosen mode and
what is actually available right now, then tries each in turn until one returns a
useful answer. Basic mode is always the final link, so Novato can never
hard-fail: if every smarter tier is unavailable or unsure, the static rules and
intent map still answer.

Chain per mode::

    basic    -> [Basic]
    offline  -> [llamafile?, Basic]
    online   -> [Groq?,      Basic]
    both     -> [Groq?, llamafile?, Basic]   (Groq primary, llamafile fallback)

A tier is only inserted if it is configured *and* available (key present /
binary present / internet reachable), so a missing Groq key silently downgrades
rather than erroring.
"""

from __future__ import annotations

import socket
from typing import Optional

from ..config import Config
from .basic_backend import BasicBackend, IntentResult
from .groq_backend import GroqBackend
from .llamafile_backend import LlamafileBackend


def internet_available(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.5) -> bool:
    """Best-effort connectivity check via a fast TCP probe to a DNS server."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Router:
    """Tries backends in priority order, falling back to Basic mode."""

    def __init__(self, backends: list) -> None:
        # Basic is guaranteed to be last; enforce it defensively.
        if not backends or backends[-1].name != "basic":
            backends = [*backends, BasicBackend()]
        self._backends = backends

    @property
    def name(self) -> str:
        """The active (highest-priority) backend's name, for the status badge."""
        return self._backends[0].name

    @property
    def chain(self) -> list[str]:
        return [b.name for b in self._backends]

    def resolve_intent(self, query: str) -> IntentResult:
        """Return the first backend's confident intent result, else Basic's."""
        last: Optional[IntentResult] = None
        for backend in self._backends:
            try:
                result = backend.resolve_intent(query)
            except Exception:
                continue
            last = result
            if result.found:
                return result
        return last or IntentResult(query)

    def analyze_error(self, ctx):
        """Return the first backend that produces a diagnosis, else None."""
        for backend in self._backends:
            analyze = getattr(backend, "analyze_error", None)
            if analyze is None:
                continue
            try:
                correction = analyze(ctx)
            except Exception:
                continue
            if correction is not None:
                return correction
        return None

    def describe(self, package: str) -> str:
        for backend in self._backends:
            desc = getattr(backend, "describe", lambda _p: "")(package)
            if desc:
                return desc
        return ""


def build_router(
    config: Config,
    *,
    check_internet: bool = True,
    _online_ok: Optional[bool] = None,
) -> Router:
    """Construct a :class:`Router` from config + live availability.

    ``_online_ok`` overrides the connectivity probe (used in tests). When the
    chosen tier isn't usable, the router quietly degrades toward Basic mode.
    """
    mode = config.mode
    backends: list = []

    want_online = mode in ("online", "both")
    want_offline = mode in ("offline", "both")

    if want_online and config.has_groq:
        online_ok = _online_ok if _online_ok is not None else (
            internet_available() if check_internet else True
        )
        if online_ok:
            groq = GroqBackend(config.groq_api_key, config.groq_model)
            if groq.available:
                backends.append(groq)

    if want_offline and config.has_llamafile:
        llama = LlamafileBackend(config.llamafile_path)
        if llama.available:
            backends.append(llama)

    backends.append(BasicBackend())
    return Router(backends)
