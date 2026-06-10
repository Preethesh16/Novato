# SPDX-License-Identifier: GPL-3.0-or-later
"""Rank search results by relevance for a beginner.

Given the user's query, the matched intent's preferred candidate order, and the
raw :class:`novato.searcher.SearchResult` list, produce an ordering that puts the
most useful, most trustworthy, most beginner-friendly option first.

The Basic-mode ranker is deterministic and dependency-free. The AI tiers may
later re-rank, but they reuse this as a sane baseline.

Signals (in rough priority):
  1. Position in the curated intent candidate list (lower index = better).
  2. Official repo over AUR/third-party (trust + no build step).
  3. Exact / prefix name match to the query.
  4. AUR popularity (tie-breaker among AUR packages).
  5. Already installed is gently de-prioritised (user likely wants new tools).
"""

from __future__ import annotations

from dataclasses import dataclass

from .searcher import SearchResult

# Repos considered "official" / no-build-step, ranked above the AUR.
_OFFICIAL_SOURCES = {"pacman", "apt", "dnf", "zypper"}


@dataclass
class RankedResult:
    """A SearchResult plus its computed relevance score and reasoning."""

    result: SearchResult
    score: float
    reasons: tuple[str, ...] = ()


def _name_match_bonus(name: str, query: str) -> float:
    """Reward results whose name matches the query text."""
    name_l = name.lower()
    q = query.lower().strip()
    if not q:
        return 0.0
    if name_l == q:
        return 1.0
    if name_l.startswith(q) or q.startswith(name_l):
        return 0.6
    if q in name_l:
        return 0.3
    return 0.0


def rank(
    results: list[SearchResult],
    *,
    query: str = "",
    preferred_order: list[str] | None = None,
    limit: int | None = None,
) -> list[RankedResult]:
    """Return results sorted best-first with explanatory scores.

    ``preferred_order`` is the curated candidate list from the intent map; a
    package's index there is the strongest signal. Unlisted packages fall to the
    end of that signal but can still rank via repo trust and name match.
    """
    preferred = {name.lower(): i for i, name in enumerate(preferred_order or [])}
    n_pref = len(preferred)
    ranked: list[RankedResult] = []

    for r in results:
        score = 0.0
        reasons: list[str] = []

        # 1. Curated order: earlier = better. Scaled to dominate other signals.
        idx = preferred.get(r.name.lower())
        if idx is not None:
            curated = (n_pref - idx) * 10.0
            score += curated
            reasons.append(f"curated #{idx + 1}")

        # 2. Official repo trust.
        if r.source in _OFFICIAL_SOURCES:
            score += 5.0
            reasons.append("official repo")
        elif r.source == "aur":
            score += 1.0
            reasons.append("AUR")

        # 3. Name match to the raw query.
        nm = _name_match_bonus(r.name, query)
        if nm:
            score += nm * 3.0
            reasons.append("name match")

        # 4. AUR popularity tie-breaker (small weight).
        if r.source == "aur" and r.popularity:
            score += min(r.popularity, 5.0) * 0.2

        # 5. Already installed: nudge down (user probably wants something new).
        if r.installed:
            score -= 0.5
            reasons.append("installed")

        ranked.append(RankedResult(r, round(score, 3), tuple(reasons)))

    ranked.sort(key=lambda rr: rr.score, reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    return ranked
