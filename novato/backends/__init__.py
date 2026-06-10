# SPDX-License-Identifier: GPL-3.0-or-later
"""AI backend implementations and the fallback router.

Three tiers, all behind a common interface:

* :mod:`basic_backend`     — difflib + rules + static intent map (always works).
* :mod:`llamafile_backend` — local offline LLM via a llamafile binary.
* :mod:`groq_backend`      — fast online inference via the free Groq API.

:mod:`router` wires them into a fallback chain (online -> offline -> basic) so
Novato never breaks: if every smarter tier is unavailable, Basic mode answers.
"""

from .basic_backend import BasicBackend, IntentResult  # noqa: F401

__all__ = ["BasicBackend", "IntentResult"]
