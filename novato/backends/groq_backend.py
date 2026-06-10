"""Online AI backend — Groq free API.

Groq runs Llama-class models on custom LPU hardware, giving ~200 ms latency and
a genuinely free tier (no credit card). This backend uses it for two jobs:

* **Intent resolution** — turn a free-text request into candidate package names.
* **Error analysis** — explain a failed command in plain English with a fix.

Privacy (safety rules #4 & #5): we send **only the intent/error text** the user
typed. We never send the user's actual commands, file paths, usernames,
hostname, environment, or distro details. The candidate names Groq returns are
then validated against the real local repositories by the searcher, so a
slightly-off name simply gets filtered out rather than mis-installed.

Network and API failures never raise into the pipeline — they return an empty /
``None`` result so the router falls through to the next tier.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .basic_backend import IntentResult

try:  # requests is a core dependency, but guard so import never hard-fails.
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_TIMEOUT = 12  # seconds
_MAX_CANDIDATES = 6

# Kept deliberately distro-agnostic to honour the privacy rule: we ask for
# common Linux package names and let the local searcher map/validate them.
_INTENT_SYSTEM_PROMPT = (
    "You are a Linux package-name resolver. Given a short description of what a "
    "user wants to do, reply with ONLY a JSON array of up to 6 real, common "
    "Linux application package names that fit, most popular and beginner-"
    "friendly first. Use lowercase canonical names (e.g. \"kdenlive\", "
    "\"firefox\"). No prose, no markdown, just the JSON array."
)

_ERROR_SYSTEM_PROMPT = (
    "You are a friendly Linux mentor for absolute beginners. Given a failed "
    "shell command and its error output, reply with ONLY a JSON object: "
    '{"title": "...", "reason": "...", "fix": "..."} where title is a short '
    "summary, reason is a 1-2 sentence plain-English explanation assuming zero "
    "Linux knowledge, and fix is a single safe command to run (or empty string "
    "if none). Never suggest rm, dd, mkfs, fdisk, or any destructive command."
)


class GroqBackend:
    """Groq-backed intent + error resolver."""

    name = "online"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile",
                 *, session=None) -> None:
        self._key = api_key
        self._model = model
        self._session = session  # injectable for tests

    @property
    def available(self) -> bool:
        return bool(self._key) and requests is not None

    # -- HTTP plumbing ------------------------------------------------------

    def _chat(self, system: str, user: str) -> Optional[str]:
        """Call Groq chat completions; return the assistant text or None."""
        if not self.available:
            return None
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 256,
        }
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        try:
            poster = self._session.post if self._session else requests.post
            resp = poster(GROQ_URL, json=payload, headers=headers, timeout=_TIMEOUT)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return None

    # -- Intent -------------------------------------------------------------

    def resolve_intent(self, query: str) -> IntentResult:
        """Ask Groq for candidate packages matching the query."""
        text = self._chat(_INTENT_SYSTEM_PROMPT, query.strip())
        candidates = _parse_package_list(text) if text else []
        if not candidates:
            return IntentResult(query, source="online")
        return IntentResult(
            query=query,
            matched_intent=query.strip().lower(),
            candidates=candidates[:_MAX_CANDIDATES],
            score=0.9,
            source="online",
        )

    def describe(self, package: str) -> str:  # noqa: D401 - parity with BasicBackend
        """Groq doesn't pre-describe; the searcher supplies real descriptions."""
        return ""

    # -- Error analysis -----------------------------------------------------

    def analyze_error(self, ctx) -> Optional["object"]:
        """Diagnose a failed command via Groq. Returns a rules.Correction."""
        from .. import rules as _rules
        from .. import safety as _safety

        user = f"Command: {ctx.command}\nExit code: {ctx.exit_code}\nError:\n{ctx.stderr}"
        text = self._chat(_ERROR_SYSTEM_PROMPT, user)
        if not text:
            return None
        obj = _parse_json_object(text)
        if not obj or "title" not in obj:
            return None
        fix = (obj.get("fix") or "").strip()
        # Enforce safety: never surface a destructive fix even if the model erred.
        if fix and not _safety.validate(fix).allowed:
            fix = ""
        return _rules.Correction(
            title=str(obj.get("title", ""))[:200],
            reason=str(obj.get("reason", ""))[:400],
            fix=fix,
            confidence=0.85,
            rule_name="groq",
        )


# ---------------------------------------------------------------------------
# Response parsing helpers (shared shape with the llamafile backend)
# ---------------------------------------------------------------------------

def _parse_package_list(text: str) -> list[str]:
    """Extract a list of package names from a model response.

    Tolerant of markdown fences and stray prose: tries a JSON array first, then
    falls back to splitting lines/commas.
    """
    if not text:
        return []
    # Prefer a JSON array if present.
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group(0))
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except json.JSONDecodeError:
            pass
    # Fallback: comma/newline separated tokens that look like package names.
    tokens = re.split(r"[,\n]", text)
    out = []
    for tok in tokens:
        tok = tok.strip().strip("-*`\"' ").lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9.+_-]{1,40}", tok):
            out.append(tok)
    return out


def _parse_json_object(text: str) -> Optional[dict]:
    """Extract the first JSON object from a model response."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
