"""Tests for backend basics (config, logging, basic backend wiring)."""

from __future__ import annotations

import os

import pytest

from novato import config as cfgmod
from novato import logger as logmod
from novato.backends.basic_backend import BasicBackend
from novato.rules import ErrorContext


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    """Point Novato's config dir at a temp directory."""
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    yield tmp_path


def test_config_roundtrip(isolated_home):
    cfg = cfgmod.load_config()
    assert cfg.mode == "basic"  # default
    cfg.mode = "both"
    cfg.groq_api_key = "secret"
    cfgmod.save_config(cfg)

    reloaded = cfgmod.load_config()
    assert reloaded.mode == "both"
    assert reloaded.has_groq is True


def test_config_file_permissions(isolated_home):
    cfg = cfgmod.load_config()
    cfg.groq_api_key = "secret"
    path = cfgmod.save_config(cfg)
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600


def test_invalid_mode_resets_to_basic(isolated_home):
    cfg = cfgmod.Config(mode="banana")
    assert cfg.mode == "basic"


def test_update_config_rejects_unknown_key(isolated_home):
    with pytest.raises(KeyError):
        cfgmod.update_config(nonsense=True)


def test_corrupt_config_falls_back(isolated_home):
    cfgmod.ensure_config_dir()
    cfgmod.config_path().write_text("{ this is not json")
    cfg = cfgmod.load_config()
    assert cfg.mode == "basic"  # graceful default


def test_logger_writes_and_reads(isolated_home):
    assert logmod.log_command("sudo pacman -S vlc") is True
    assert logmod.log_command("sudo apt install vlc", dry_run=True) is True
    lines = logmod.read_history()
    assert any("EXEC" in ln and "pacman" in ln for ln in lines)
    assert any("DRYRUN" in ln for ln in lines)


def test_logger_flattens_newlines(isolated_home):
    logmod.log_event(logmod.EVENT_EXEC, "echo a\necho b")
    last = logmod.read_history(limit=1)[0]
    assert "\n" not in last.replace("\\n", "")
    assert "echo a echo b" in last


def test_basic_backend_analyze_error(isolated_home):
    backend = BasicBackend()
    ctx = ErrorContext(
        command="sudo pacmna -S vlc",
        exit_code=127,
        stderr="pacmna: command not found",
        distro_id="arch",
        package_manager="pacman",
        install_cmd="sudo pacman -S",
    )
    correction = backend.analyze_error(ctx)
    assert correction is not None
    assert correction.fix == "sudo pacman -S vlc"
