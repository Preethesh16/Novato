"""Tests for repository search parsing and ranking."""

from __future__ import annotations

from novato import searcher
from novato.ranker import rank
from novato.searcher import SearchResult


# -- pacman parsing ---------------------------------------------------------

def test_parse_pacman_output(monkeypatch):
    sample = (
        "extra/vlc 3.0.20-4 [installed]\n"
        "    A free and open source cross-platform multimedia player\n"
        "extra/mpv 0.38.0-1\n"
        "    a free, open source, and cross-platform media player\n"
    )
    monkeypatch.setattr(searcher, "_run", lambda cmd: (0, sample, ""))
    results = searcher.search_pacman("media player")
    assert len(results) == 2
    vlc = results[0]
    assert vlc.name == "vlc"
    assert vlc.repo == "extra"
    assert vlc.version == "3.0.20-4"
    assert vlc.installed is True
    assert "multimedia player" in vlc.description
    assert results[1].installed is False


def test_pacman_missing_binary(monkeypatch):
    monkeypatch.setattr(searcher, "_run", lambda cmd: (127, "", "not found"))
    assert searcher.search_pacman("vlc") == []


# -- apt parsing ------------------------------------------------------------

def test_parse_apt_output(monkeypatch):
    sample = (
        "vlc - multimedia player and streamer\n"
        "mpv - video player based on MPlayer/mplayer2\n"
    )
    monkeypatch.setattr(searcher, "_run", lambda cmd: (0, sample, ""))
    results = searcher.search_apt("player")
    assert {r.name for r in results} == {"vlc", "mpv"}
    assert results[0].description == "multimedia player and streamer"


# -- dnf parsing ------------------------------------------------------------

def test_parse_dnf_output(monkeypatch):
    sample = (
        "================ Name Matched: vlc ================\n"
        "vlc.x86_64 : The cross-platform open-source multimedia framework\n"
    )
    monkeypatch.setattr(searcher, "_run", lambda cmd: (0, sample, ""))
    results = searcher.search_dnf("vlc")
    assert len(results) == 1
    assert results[0].name == "vlc"  # arch suffix stripped


# -- AUR JSON parsing -------------------------------------------------------

def test_parse_aur_json():
    raw = (
        '{"resultcount":1,"type":"search","results":['
        '{"Name":"davinci-resolve","Version":"19.0-1",'
        '"Description":"Professional video editor","Popularity":12.3,'
        '"NumVotes":340,"Maintainer":"someone"}]}'
    )
    results = searcher._parse_aur_json(raw)
    assert len(results) == 1
    r = results[0]
    assert r.name == "davinci-resolve"
    assert r.repo == "AUR"
    assert r.popularity == 12.3
    assert r.extra["votes"] == 340


def test_parse_aur_error_response():
    raw = '{"type":"error","error":"something"}'
    assert searcher._parse_aur_json(raw) == []


def test_aur_network_failure_returns_empty():
    def boom(url):
        raise OSError("no network")
    assert searcher.search_aur("vlc", opener=boom) == []


# -- dedup + dispatch -------------------------------------------------------

def test_search_dedups_by_name(monkeypatch):
    monkeypatch.setattr(searcher, "search_pacman",
                        lambda q: [SearchResult(name="vlc", source="pacman")])
    monkeypatch.setattr(searcher, "search_aur",
                        lambda q, **k: [SearchResult(name="vlc", source="aur"),
                                        SearchResult(name="vlc-bin", source="aur")])
    results = searcher.search("vlc", "pacman", include_aur=True)
    names = [r.name for r in results]
    assert names.count("vlc") == 1  # deduped
    assert "vlc-bin" in names


# -- ranking ----------------------------------------------------------------

def test_rank_prefers_curated_order():
    results = [
        SearchResult(name="shotcut", source="pacman", repo="extra"),
        SearchResult(name="kdenlive", source="pacman", repo="extra"),
    ]
    ranked = rank(results, query="edit video",
                  preferred_order=["kdenlive", "shotcut"])
    assert ranked[0].result.name == "kdenlive"


def test_rank_prefers_official_over_aur():
    results = [
        SearchResult(name="brave", source="aur", repo="AUR", popularity=20),
        SearchResult(name="firefox", source="pacman", repo="extra"),
    ]
    ranked = rank(results, query="browser", preferred_order=[])
    assert ranked[0].result.name == "firefox"


def test_rank_name_match_bonus():
    results = [
        SearchResult(name="vlc", source="pacman", repo="extra"),
        SearchResult(name="vlc-plugin-extra", source="pacman", repo="extra"),
    ]
    ranked = rank(results, query="vlc", preferred_order=[])
    assert ranked[0].result.name == "vlc"
