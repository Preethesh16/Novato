"""Tests for the AI backends and the fallback router."""

from __future__ import annotations

import pytest

from novato.backends import groq_backend as gb
from novato.backends.basic_backend import BasicBackend
from novato.backends.groq_backend import GroqBackend
from novato.backends.llamafile_backend import LlamafileBackend, select_model
from novato.backends.router import Router, build_router
from novato.config import Config
from novato.rules import ErrorContext


# -- response parsing -------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ('["kdenlive", "shotcut"]', ["kdenlive", "shotcut"]),
    ('Here you go:\n["vlc","mpv"]', ["vlc", "mpv"]),
    ("vlc, mpv, celluloid", ["vlc", "mpv", "celluloid"]),
    ("- firefox\n- chromium", ["firefox", "chromium"]),
    ("", []),
])
def test_parse_package_list(text, expected):
    assert gb._parse_package_list(text) == expected


def test_parse_json_object():
    text = 'noise {"title":"t","reason":"r","fix":"sudo pacman -S vlc"} trailing'
    obj = gb._parse_json_object(text)
    assert obj["title"] == "t"
    assert obj["fix"] == "sudo pacman -S vlc"


# -- Groq backend (injected session) ----------------------------------------

class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        return self._resp


def _groq_with_content(content):
    resp = _FakeResp(200, {"choices": [{"message": {"content": content}}]})
    return GroqBackend("fake-key", session=_FakeSession(resp))


def test_groq_resolve_intent():
    backend = _groq_with_content('["kdenlive","shotcut","openshot"]')
    result = backend.resolve_intent("edit videos")
    assert result.found
    assert result.candidates[0] == "kdenlive"
    assert result.source == "online"


def test_groq_error_analysis_blocks_destructive_fix():
    # Even if the model returns a destructive fix, safety must strip it.
    backend = _groq_with_content('{"title":"oops","reason":"bad","fix":"rm -rf /"}')
    ctx = ErrorContext(command="foo", exit_code=1, stderr="boom")
    correction = backend.analyze_error(ctx)
    assert correction is not None
    assert correction.fix == ""  # destructive fix removed


def test_groq_http_error_returns_empty():
    resp = _FakeResp(401, {})
    backend = GroqBackend("bad", session=_FakeSession(resp))
    assert backend.resolve_intent("edit videos").found is False


def test_groq_unavailable_without_key():
    assert GroqBackend("").available is False


# -- llamafile backend ------------------------------------------------------

@pytest.mark.parametrize("ram,expected_model", [
    (2, "phi3:mini"),
    (6, "phi3"),
    (12, "llama3.2"),
    (32, "llama3.1"),
])
def test_select_model_by_ram(ram, expected_model):
    assert select_model(ram)[0] == expected_model


def test_llamafile_with_injected_runner():
    backend = LlamafileBackend("", runner=lambda prompt: '["vlc","mpv"]')
    assert backend.available is True
    result = backend.resolve_intent("watch videos")
    assert "vlc" in result.candidates
    assert result.source == "offline"


def test_llamafile_unavailable_without_binary():
    assert LlamafileBackend("/nonexistent/path").available is False


# -- router fallback chain --------------------------------------------------

def test_router_always_ends_with_basic():
    r = Router([])  # empty -> basic appended
    assert r.chain == ["basic"]


def test_router_falls_through_to_basic_when_ai_empty():
    class _Empty:
        name = "online"

        def resolve_intent(self, q):
            from novato.backends.basic_backend import IntentResult
            return IntentResult(q, source="online")  # not found

    r = Router([_Empty(), BasicBackend()])
    result = r.resolve_intent("edit videos")
    # Basic mode rescued it.
    assert result.found
    assert "kdenlive" in result.candidates


def test_build_router_basic_mode():
    r = build_router(Config(mode="basic"))
    assert r.chain == ["basic"]


def test_build_router_online_without_key_degrades():
    r = build_router(Config(mode="online"), check_internet=False)
    assert r.chain == ["basic"]  # no key -> no Groq tier


def test_build_router_online_with_key():
    cfg = Config(mode="online", groq_api_key="abc")
    r = build_router(cfg, check_internet=False, _online_ok=True)
    assert r.chain == ["online", "basic"]


def test_build_router_both_with_everything(tmp_path):
    binpath = tmp_path / "model.llamafile"
    binpath.write_text("#!/bin/sh\n")
    binpath.chmod(0o755)
    cfg = Config(mode="both", groq_api_key="abc", llamafile_path=str(binpath))
    r = build_router(cfg, check_internet=False, _online_ok=True)
    assert r.chain == ["online", "offline", "basic"]
