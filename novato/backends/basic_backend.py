# SPDX-License-Identifier: GPL-3.0-or-later
"""Basic mode backend — zero dependencies, always available.

This tier is the bedrock of Novato's "offline first" promise. It answers two
kinds of questions with nothing but the Python standard library:

* **Intent -> packages**: fuzzy-matches a plain-English request against the
  static :data:`novato.intent_map.INTENT_MAP` using :mod:`difflib`.
* **Error -> fix**: delegates to the rule engine in :mod:`novato.rules`.

It handles roughly 80% of real-world use cases instantly (milliseconds, ~5MB
RAM) and 100% privately — nothing leaves the machine. The smarter tiers
(llamafile, Groq) layer on top via the router but always fall back here.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .. import intent_map as _im
from .. import rules as _rules

# Filler words stripped from a query before matching, so "i want to edit my
# videos please" reduces to the signal: "edit videos".
_STOPWORDS = frozenset({
    "i", "want", "to", "a", "an", "the", "my", "some", "please", "need",
    "would", "like", "can", "you", "help", "me", "install", "get", "find",
    "for", "with", "app", "application", "program", "software", "tool",
    "that", "lets", "let", "is", "are", "of", "on", "this", "novato",
})


@dataclass
class IntentResult:
    """Outcome of an intent lookup."""

    query: str
    matched_intent: str = ""           # The intent key we matched, if any.
    candidates: list[str] = field(default_factory=list)
    score: float = 0.0                 # Match confidence 0..1.
    source: str = "basic"

    @property
    def found(self) -> bool:
        return bool(self.candidates)


def normalize_query(query: str) -> str:
    """Lowercase, strip punctuation, and drop filler words from a query."""
    query = query.lower()
    query = re.sub(r"[^a-z0-9\s]", " ", query)
    tokens = [t for t in query.split() if t and t not in _STOPWORDS]
    # Light singularisation so "videos" matches "video".
    tokens = [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens]
    return " ".join(tokens)


class BasicBackend:
    """Rule- and dictionary-based backend. Stateless and instant."""

    name = "basic"

    def __init__(self, intents: dict[str, list[str]] | None = None) -> None:
        self._intents = intents if intents is not None else _im.INTENT_MAP
        # Pre-normalise intent keys once for matching.
        self._normalized_keys = {normalize_query(k): k for k in self._intents}

    # -- Intent resolution --------------------------------------------------

    def resolve_intent(self, query: str) -> IntentResult:
        """Map a natural-language query to candidate packages.

        Strategy (cheapest first):
          1. Exact match on the raw key.
          2. Exact match on the normalised query.
          3. Substring / token-overlap match.
          4. Fuzzy (difflib) match against normalised keys.
        """
        raw = query.strip().lower()
        if raw in self._intents:
            return IntentResult(query, raw, list(self._intents[raw]), 1.0)

        norm = normalize_query(query)
        if not norm:
            return IntentResult(query)

        if norm in self._normalized_keys:
            key = self._normalized_keys[norm]
            return IntentResult(query, key, list(self._intents[key]), 0.97)

        # Token-overlap: pick the intent sharing the most words with the query.
        # Only short-circuit when the query *fully* covers an intent's words
        # (score == 1.0); a partial overlap is ambiguous (e.g. "edit ___") and
        # should compete with the fuzzy match below.
        overlap = self._token_overlap(norm)
        if overlap is not None and overlap[1] >= 1.0:
            key, score = overlap
            return IntentResult(query, key, list(self._intents[key]), score)

        # Fuzzy match on the whole normalised string (catches typos like
        # "edit vidio" -> "edit video").
        fuzzy = None
        matches = difflib.get_close_matches(
            norm, list(self._normalized_keys), n=1, cutoff=0.6
        )
        if matches:
            key = self._normalized_keys[matches[0]]
            score = difflib.SequenceMatcher(None, norm, matches[0]).ratio()
            fuzzy = (key, round(score, 2))

        # Pick whichever of {token-overlap, fuzzy} is more confident.
        best = max(
            [c for c in (overlap, fuzzy) if c is not None],
            key=lambda c: c[1],
            default=None,
        )
        if best is not None and best[1] > 0:
            key, score = best
            return IntentResult(query, key, list(self._intents[key]), score)

        return IntentResult(query)

    def _token_overlap(self, norm_query: str) -> tuple[str, float] | None:
        """Return the intent with the highest token-overlap ratio, or None."""
        q_tokens = set(norm_query.split())
        if not q_tokens:
            return None
        best_key = None
        best_score = 0.0
        best_overlap = 0
        for norm_key, original in self._normalized_keys.items():
            k_tokens = set(norm_key.split())
            if not k_tokens:
                continue
            overlap = len(q_tokens & k_tokens)
            if not overlap:
                continue
            # Jaccard-ish: reward covering the intent's words.
            score = overlap / len(k_tokens)
            # On a score tie, prefer the intent that matches *more* of the
            # query's words (more specific), e.g. "qr code" over bare "code"
            # for the query "make a qr code"; only then fall back to the
            # shorter key.
            better = (
                score > best_score
                or (score == best_score and overlap > best_overlap)
                or (score == best_score and overlap == best_overlap
                    and best_key is not None and len(norm_key) < len(best_key))
            )
            if better:
                best_score = score
                best_overlap = overlap
                best_key = original  # original (un-normalised) key
        if best_key is None:
            return None
        return best_key, round(best_score, 2)

    def describe(self, package: str) -> str:
        """Return a short description for a package (may be empty)."""
        return _im.describe(package)

    # -- Error analysis -----------------------------------------------------

    def analyze_error(self, ctx: "_rules.ErrorContext"):
        """Diagnose a failed command using the rule engine.

        Returns a :class:`novato.rules.Correction` or ``None``.
        """
        return _rules.analyze(ctx)
