"""Tests for the first-run setup wizard."""

from __future__ import annotations

import pytest

from novato import config as cfgmod
from novato.detector import SystemInfo
from novato.presenter import Presenter
from novato.setup_wizard import SetupWizard


@pytest.fixture()
def arch_system():
    return SystemInfo(
        distro_id="arch", distro_name="Arch Linux", distro_version="",
        package_manager="pacman", install_cmd="sudo pacman -S",
        search_cmd="pacman -Ss", supports_aur=True, aur_helper="yay",
        shell="zsh", supported=True,
    )


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    yield tmp_path


def _wizard(arch_system, answers, *, verify=lambda k: True):
    it = iter(answers)
    presenter = Presenter(input_fn=lambda prompt: next(it, ""))
    return SetupWizard(
        system=arch_system,
        presenter=presenter,
        input_fn=lambda prompt: next(it, ""),
        verify_groq=verify,
        open_browser=lambda url: True,
    )


def test_skip_stays_basic(arch_system, isolated_home):
    # _wizard shares one iterator via presenter; build explicitly here.
    answers = iter(["s"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
    )
    cfg = w.run()
    assert cfg.mode == "basic"
    assert cfg.setup_complete is True
    assert cfgmod.load_config().mode == "basic"


def test_online_with_valid_key(arch_system, isolated_home):
    answers = iter(["2", "gsk_validkey"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
    )
    cfg = w.run()
    assert cfg.mode == "online"
    assert cfg.groq_api_key == "gsk_validkey"


def test_online_blank_key_degrades_to_basic(arch_system, isolated_home):
    answers = iter(["2", ""])  # choose online but provide no key
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
    )
    cfg = w.run()
    assert cfg.mode == "basic"  # no usable tier -> basic
    assert cfg.has_groq is False


def test_both_mode_sets_model_and_key(arch_system, isolated_home):
    answers = iter(["3", "gsk_key"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
    )
    cfg = w.run()
    # llamafile binary not provided, but Groq key is -> "both" still valid.
    assert cfg.mode == "both"
    assert cfg.groq_api_key == "gsk_key"
    assert cfg.llamafile_model  # a model was selected for the offline tier
