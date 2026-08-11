# SPDX-License-Identifier: GPL-3.0-or-later
"""Redaction applied before local evidence is sent to an online model."""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path
from typing import Any

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*"
    r"([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_CREDENTIAL_URL = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")
_HOME_PATH = re.compile(r"/home/[^/\s]+")
_ROOT_PATH = re.compile(r"/root(?=/|\s|$)")
_NAMED_USER = re.compile(r"(?i)\b(user(?:name)?|owner)\s*[:=]\s*[A-Za-z_][\w.-]*")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_MAC = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])")


def redact_text(value: str) -> str:
    """Remove common identities, paths, and credentials from free text."""
    text = str(value)
    home = str(Path.home())
    username = os.environ.get("USER", "")
    hostname = socket.gethostname()
    if home and home != "/":
        text = text.replace(home, "<HOME>")
    if username:
        text = re.sub(rf"\b{re.escape(username)}\b", "<USER>", text)
    if hostname:
        text = re.sub(rf"\b{re.escape(hostname)}\b", "<HOST>", text)
    text = _HOME_PATH.sub("<HOME>", text)
    text = _ROOT_PATH.sub("<HOME>", text)
    text = _BEARER.sub("Bearer <REDACTED>", text)
    text = _CREDENTIAL_URL.sub(r"\1<REDACTED>@", text)
    text = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=<REDACTED>", text)
    text = _NAMED_USER.sub(lambda m: f"{m.group(1)}=<USER>", text)
    text = _IPV4.sub("<IP>", text)
    text = _MAC.sub("<MAC>", text)
    return text


def redact(value: Any) -> Any:
    """Recursively redact a JSON-like value."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in (
                "password", "passwd", "secret", "token", "api_key", "authorization",
            )):
                cleaned[key] = "<REDACTED>"
            else:
                cleaned[key] = redact(item)
        return cleaned
    return value
