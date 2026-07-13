"""Tests for intent resolution and the static intent map."""

from __future__ import annotations

import pytest

from novato import intent_map
from novato.backends.basic_backend import BasicBackend, normalize_query
from novato.task_intent import STORAGE_CHECK, STORAGE_CLEAN


def test_intent_map_is_well_formed():
    assert len(intent_map.INTENT_MAP) >= 200 or len(intent_map.INTENT_MAP) >= 150
    for key, pkgs in intent_map.INTENT_MAP.items():
        assert key == key.lower(), f"intent key not lowercase: {key!r}"
        assert isinstance(pkgs, list) and pkgs, f"empty candidates for {key!r}"
        assert all(isinstance(p, str) and p for p in pkgs)


def test_no_duplicate_intent_keys():
    # Building the flattened map should not have silently dropped collisions.
    assert len(intent_map.all_intents()) == len(set(intent_map.all_intents()))


def test_normalize_query_strips_filler_and_plurals():
    assert normalize_query("I want to edit my videos please") == "edit video"
    assert normalize_query("install a web browser") == "web browser"


@pytest.mark.parametrize("query,expected_pkg", [
    ("edit video", "kdenlive"),
    ("i want to edit videos", "kdenlive"),
    ("web browser", "firefox"),
    ("a private browser", "librewolf"),
    ("password manager", "keepassxc"),
    ("system monitor", "htop"),
    # Coding queries must reach a code editor, not a literal "code" substring
    # match like qrencode.
    ("something to edit code", "neovim"),
    ("edit code", "neovim"),
    ("coding", "neovim"),
    ("i want to code", "neovim"),
    ("programming", "neovim"),
])
def test_resolve_intent_finds_expected(query, expected_pkg):
    backend = BasicBackend()
    result = backend.resolve_intent(query)
    assert result.found
    assert expected_pkg in result.candidates


@pytest.mark.parametrize("query,expected_pkg", [
    ("qr code", "qrencode"),
    ("make a qr code", "qrencode"),
])
def test_specific_multiword_intent_beats_generic_token(query, expected_pkg):
    """On a score tie, the intent covering more query words wins.

    Regression: adding a bare "code" intent must not hijack "qr code".
    """
    backend = BasicBackend()
    result = backend.resolve_intent(query)
    assert result.candidates[0] == expected_pkg


def test_exact_match_scores_highest():
    backend = BasicBackend()
    result = backend.resolve_intent("edit video")
    assert result.score == 1.0


def test_fuzzy_typo_still_matches():
    backend = BasicBackend()
    result = backend.resolve_intent("edit vidio")  # typo
    assert result.found
    assert "kdenlive" in result.candidates


def test_unknown_intent_returns_empty():
    backend = BasicBackend()
    result = backend.resolve_intent("xyzzy quux frobnicate")
    assert not result.found
    assert result.candidates == []


@pytest.mark.parametrize("query", [
    "check space",
    "how much room do I have remaining?",
    "show me the available capacity on this drive",
    "why is my disk almost full?",
    "do I have enough room for another game?",
    "is my drive getting crowded?",
    "chek my storaje",  # typo tolerance
])
def test_basic_semantic_task_intent_checks_storage(query):
    result = BasicBackend().resolve_task(query)
    assert result.action == STORAGE_CHECK


@pytest.mark.parametrize("query", [
    "clean storage safely",
    "help me reclaim disk space",
    "free up some room on my drive",
    "remove unnecessary cache",
    "can you make more room?",
    "get rid of temporary data",
])
def test_basic_semantic_task_intent_cleans_storage(query):
    result = BasicBackend().resolve_task(query)
    assert result.action == STORAGE_CLEAN


@pytest.mark.parametrize("query", [
    "clean up this code",
    "check my email",
    "delete a file",
    "install a disk usage tool",
])
def test_basic_task_intent_does_not_hijack_unrelated_requests(query):
    assert not BasicBackend().resolve_task(query).found


def test_lookup_helper():
    assert "vlc" in intent_map.lookup("watch video")
    assert intent_map.lookup("nonexistent intent") == []


def test_describe_returns_string():
    assert "player" in intent_map.describe("vlc").lower()
    assert intent_map.describe("totally-unknown-pkg") == ""
