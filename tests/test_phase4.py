"""Tests for the /mistake hook lifecycle, /explain teacher, /switch switcher."""

from __future__ import annotations

import pytest

from novato import config as cfgmod
from novato import switcher
from novato import watcher
from novato.switcher import ModeSwitchError
from novato.teacher import Teacher


# -- watcher: shell-hook lifecycle -----------------------------------------

@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_install_then_uninstall_hook(tmp_path, shell):
    rc = tmp_path / f".{shell}rc"
    rc.write_text("# my existing config\nexport PATH=$PATH:/foo\n")

    assert watcher.is_installed(shell, rc_file=rc) is False

    changed, msg = watcher.install_hook(shell, rc_file=rc)
    assert changed is True
    assert watcher.is_installed(shell, rc_file=rc) is True
    assert "novato --analyze-error" in rc.read_text()
    # Existing config is preserved.
    assert "my existing config" in rc.read_text()

    # Idempotent: installing again does nothing.
    changed2, _ = watcher.install_hook(shell, rc_file=rc)
    assert changed2 is False
    assert rc.read_text().count(watcher.BEGIN_MARKER) == 1

    # Remove cleanly.
    removed, _ = watcher.uninstall_hook(shell, rc_file=rc)
    assert removed is True
    assert watcher.is_installed(shell, rc_file=rc) is False
    assert "my existing config" in rc.read_text()
    assert watcher.BEGIN_MARKER not in rc.read_text()


def test_uninstall_when_absent_is_noop(tmp_path):
    rc = tmp_path / ".zshrc"
    rc.write_text("echo hi\n")
    changed, _ = watcher.uninstall_hook("zsh", rc_file=rc)
    assert changed is False
    assert rc.read_text() == "echo hi\n"


def test_unsupported_shell():
    assert watcher.supported_shell("fish") is False
    changed, msg = watcher.install_hook("fish", rc_file=None)
    assert changed is False
    assert "fish" in msg


def test_hook_snippet_contains_markers():
    snip = watcher.hook_snippet("zsh")
    assert watcher.BEGIN_MARKER in snip and watcher.END_MARKER in snip


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_hook_ignores_signal_exits(shell):
    # Ctrl+C (130) / kill (143) are deliberate — the hook must not fire on them.
    assert "-lt 128" in watcher.hook_snippet(shell)


@pytest.mark.parametrize("shell", ["zsh", "bash"])
def test_install_hook_upgrades_outdated_block(tmp_path, shell):
    # An rc file with an OLD hook version (no signal guard) must be upgraded
    # in place, preserving the surrounding config.
    rc = tmp_path / f".{shell}rc"
    old_block = (
        f"{watcher.BEGIN_MARKER}\n"
        "novato_mistake_handler() { old version without signal guard; }\n"
        f"{watcher.END_MARKER}"
    )
    rc.write_text(f"# my config\n\n{old_block}\n\nexport PATH=$PATH:/foo\n")

    changed, msg = watcher.install_hook(shell, rc_file=rc)
    assert changed is True
    assert "Updated" in msg
    content = rc.read_text()
    assert content.count(watcher.BEGIN_MARKER) == 1
    assert "old version without signal guard" not in content
    assert "-lt 128" in content
    assert "# my config" in content and "export PATH=$PATH:/foo" in content

    # Re-running with the current version is a no-op again.
    changed2, _ = watcher.install_hook(shell, rc_file=rc)
    assert changed2 is False


# -- teacher: /explain ------------------------------------------------------

def test_teacher_explains_pacman_install():
    parts = Teacher().explain_command("sudo pacman -S vlc", package="vlc")
    assert parts["sudo"].startswith("run as administrator")
    assert "Arch" in parts["pacman"]
    assert "-S" in parts
    assert parts["vlc"].startswith("the exact package")
    # Reading order: sudo first, package last.
    keys = list(parts)
    assert keys[0] == "sudo" and keys[-1] == "vlc"


def test_teacher_explains_apt_install():
    parts = Teacher().explain_command("sudo apt install firefox", package="firefox")
    assert "apt" in parts
    assert parts["install"] == "install the named package"


def test_teacher_empty_command():
    assert Teacher().explain_command("") == {}


# -- switcher: /switch ------------------------------------------------------

@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    yield tmp_path


def test_switch_persists(isolated_home):
    cfg = switcher.switch("online")
    assert cfg.mode == "online"
    assert cfgmod.load_config().mode == "online"


def test_switch_invalid_raises(isolated_home):
    with pytest.raises(ModeSwitchError):
        switcher.switch("banana")


def test_mode_menu_covers_all_modes():
    modes = [m for m, _ in switcher.mode_menu()]
    assert set(modes) == set(cfgmod.VALID_MODES)
    # Online is recommended: installs/updates need the internet anyway, and Groq
    # needs no multi-GB model download to get started.
    assert switcher.RECOMMENDED_MODE == "online"
    assert switcher.RECOMMENDED_MODE in cfgmod.VALID_MODES
