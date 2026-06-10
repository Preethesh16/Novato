"""Tests for the first-run setup wizard."""

from __future__ import annotations

import pytest

from novato import config as cfgmod
from novato.detector import SystemInfo
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


# A no-op hook installer so tests never touch the real ~/.zshrc. Returns the
# (changed, message) shape the wizard expects.
_STUB_HOOK = lambda shell: (True, "stub-installed")  # noqa: E731


def test_skip_stays_basic(arch_system, isolated_home):
    # Skip AI, then accept the mistake-watcher (blank answer -> default yes).
    answers = iter(["s"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "basic"
    assert cfg.setup_complete is True
    assert cfg.mistake is True  # watcher enabled during onboarding
    assert cfgmod.load_config().mode == "basic"


def test_skip_declining_watcher(arch_system, isolated_home):
    # Skip AI and decline the mistake-watcher -> mistake stays off.
    answers = iter(["s", "n"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "basic"
    assert cfg.mistake is False


def test_online_with_valid_key(arch_system, isolated_home):
    answers = iter(["2", "gsk_validkey"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        install_hook_fn=_STUB_HOOK,
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
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "basic"  # no usable tier -> basic
    assert cfg.has_groq is False


def test_both_declining_download_degrades_to_online(arch_system, isolated_home):
    # Choose "both", pick model 1 (tinyllama), decline the download, then paste a key.
    # With no model on disk, "both" honestly degrades to "online".
    answers = iter(["3", "1", "n", "gsk_key"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        download_fn=lambda spec, ui: None,  # never hit the network
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "online"  # offline tier not configured -> online only
    assert cfg.groq_api_key == "gsk_key"
    assert cfg.llamafile_model  # a model was still selected/recorded for later


def test_both_with_model_and_key_stays_both(arch_system, isolated_home, tmp_path):
    # Accept the download (stubbed) and provide a key -> full "both" mode.
    fake = tmp_path / "model.llamafile"
    fake.write_text("#!/bin/sh\n")
    answers = iter(["3", "1", "y", "gsk_key"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        download_fn=lambda spec, ui: fake,
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "both"
    assert cfg.groq_api_key == "gsk_key"
    assert cfg.llamafile_path == str(fake)


def test_offline_declining_download_stays_basic(arch_system, isolated_home):
    # Pick offline but decline the download -> nothing usable -> Basic mode.
    answers = iter(["1", "n"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        download_fn=lambda spec, ui: None,
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "basic"  # optional download declined -> safe default


def test_offline_mode_downloads_model(arch_system, isolated_home, tmp_path):
    # Choose offline, accept the download; download_fn is stubbed to a fake path.
    fake = tmp_path / "model.llamafile"
    fake.write_text("#!/bin/sh\n")
    answers = iter(["1", "1", "y"])
    w = SetupWizard(
        system=arch_system,
        input_fn=lambda p: next(answers, ""),
        verify_groq=lambda k: True,
        open_browser=lambda u: True,
        download_fn=lambda spec, ui: fake,
        install_hook_fn=_STUB_HOOK,
    )
    cfg = w.run()
    assert cfg.mode == "offline"
    assert cfg.llamafile_path == str(fake)
