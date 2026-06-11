"""Tests for installed-package detection and origin attribution."""

from __future__ import annotations

from novato import installed


def test_installed_versions_pacman(monkeypatch):
    out = "firefox 151.0.4-1\nbrave-bin 1.85.115-1\n"
    monkeypatch.setattr(installed, "_run", lambda cmd: (0, out, ""))
    versions = installed.installed_versions("pacman")
    assert versions["firefox"] == "151.0.4-1"
    assert versions["brave-bin"] == "1.85.115-1"


def test_installed_versions_unknown_pm():
    assert installed.installed_versions("nix") == {}


def test_installed_versions_error_is_empty(monkeypatch):
    monkeypatch.setattr(installed, "_run", lambda cmd: (1, "", "boom"))
    assert installed.installed_versions("pacman") == {}


def _fake_pacman_run(cmd):
    if cmd == ["pacman", "-Q"]:
        return 0, "brave-bin 1.85.115-1\nfirefox 151.0.4-1\n", ""
    if cmd == ["pacman", "-Qm"]:
        return 0, "brave-bin 1.85.115-1\n", ""
    return 1, "", ""


def test_get_info_attributes_aur_origin(monkeypatch):
    monkeypatch.setattr(installed, "_run", _fake_pacman_run)
    info = installed.get_info("brave-bin", "pacman")
    assert info is not None
    assert info.version == "1.85.115-1"
    assert info.origin == installed.ORIGIN_AUR


def test_get_info_official_origin(monkeypatch):
    monkeypatch.setattr(installed, "_run", _fake_pacman_run)
    info = installed.get_info("firefox", "pacman")
    assert info is not None
    assert info.origin == installed.ORIGIN_OFFICIAL


def test_get_info_not_installed(monkeypatch):
    monkeypatch.setattr(installed, "_run", _fake_pacman_run)
    assert installed.get_info("vlc", "pacman") is None
