"""Tests for the teaching engine, including arbitrary-command explanations."""

from __future__ import annotations

from novato.teacher import Teacher


def test_explain_arbitrary_command_breaks_down_flags_and_paths():
    parts = Teacher().explain_arbitrary_command("ls -la /etc")
    assert list(parts) == ["ls", "-la", "/etc"]
    assert "folder" in parts["ls"]
    assert "/etc" in parts and "configuration" in parts["/etc"]


def test_explain_arbitrary_command_handles_sudo_and_danger():
    parts = Teacher().explain_arbitrary_command("sudo rm -rf /tmp/x")
    assert parts["sudo"].startswith("run as administrator")
    assert "delete" in parts["rm"]
    assert "dangerous" in parts["-rf"]


def test_explain_arbitrary_command_unknown_path_and_flag_fallbacks():
    parts = Teacher().explain_arbitrary_command("frobnicate --wibble /opt/thing")
    # Unknown program -> nothing to say about it (left out).
    assert "frobnicate" not in parts
    # Unknown flag and path still get generic explanations.
    assert "--wibble" in parts
    assert "/opt/thing" in parts


def test_explain_arbitrary_command_empty():
    assert Teacher().explain_arbitrary_command("") == {}


def test_explain_chmod_numeric_mode():
    parts = Teacher().explain_arbitrary_command("chmod 755 script.sh")
    assert "755" in parts
    meaning = parts["755"]
    assert "owner: read/write/run" in meaning
    assert "group: read/run" in meaning
    assert "others: read/run" in meaning


def test_explain_chmod_640_mode():
    parts = Teacher().explain_arbitrary_command("chmod 640 secret.txt")
    assert "others: nothing" in parts["640"]


def test_install_explain_still_works():
    parts = Teacher().explain_command("sudo pacman -S vlc", package="vlc")
    assert parts["sudo"].startswith("run as administrator")
    assert "vlc" in parts
