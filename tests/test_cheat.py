"""Tests for the /cheat command reference."""

from __future__ import annotations

from novato import cheat


def test_every_category_has_rows():
    for name in cheat.categories():
        rows = cheat.get(name)
        assert rows, f"empty cheat-sheet: {name}"
        assert all(len(r) == 2 and r[0] and r[1] for r in rows)


def test_every_category_has_a_blurb():
    for name in cheat.categories():
        assert cheat.CATEGORY_BLURBS.get(name)


def test_resolve_category_exact_prefix_and_synonym():
    assert cheat.resolve_category("files") == "files"
    assert cheat.resolve_category("nav") == "navigation"
    assert cheat.resolve_category("keyboard") == "shortcuts"
    assert cheat.resolve_category("net") == "network"


def test_resolve_category_unknown_returns_none():
    assert cheat.resolve_category("nonsense") is None
    assert cheat.resolve_category("") is None


def test_get_unknown_category_is_empty():
    assert cheat.get("does-not-exist") == []
