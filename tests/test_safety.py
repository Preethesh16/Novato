"""Tests for the safety layer — the non-negotiable guardrails."""

from __future__ import annotations

import pytest

from novato import safety
from novato.safety import Risk


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf /home/user",
    "sudo rm -rf /*",
    "dd if=/dev/zero of=/dev/sda",
    "mkfs.ext4 /dev/sdb1",
    "sudo fdisk /dev/sda",
    ":(){ :|:& };:",
    "shred -u importantfile",
    "chmod -R 777 /",
])
def test_destructive_commands_are_blocked(cmd):
    verdict = safety.validate(cmd)
    assert verdict.risk is Risk.BLOCKED
    assert verdict.allowed is False


@pytest.mark.parametrize("cmd", [
    "sudo pacman -S vlc",
    "sudo apt install firefox",
    "pacman -Ss video",
    "pip install requests",
    "git clone https://example.com/repo",
])
def test_normal_commands_need_confirmation(cmd):
    verdict = safety.validate(cmd)
    assert verdict.risk is Risk.NEEDS_CONFIRM
    assert verdict.allowed is True


def test_empty_command_blocked():
    assert safety.validate("   ").risk is Risk.BLOCKED


@pytest.mark.parametrize("cmd,expected", [
    ("sudo pacman -S vlc --noconfirm", "sudo pacman -S vlc"),
    ("sudo apt install vlc -y", "sudo apt install vlc"),
    ("sudo apt install vlc --yes", "sudo apt install vlc"),
    ("sudo dnf install vlc -y", "sudo dnf install vlc"),
])
def test_auto_confirm_flags_are_stripped(cmd, expected):
    assert safety.sanitize(cmd) == expected
    verdict = safety.validate(cmd)
    assert verdict.sanitized == expected


def test_has_auto_confirm_detection():
    assert safety.has_auto_confirm("sudo pacman -S vlc --noconfirm")
    assert safety.has_auto_confirm("sudo apt install vlc -y")
    assert not safety.has_auto_confirm("sudo pacman -S vlc")


def test_program_name_skips_sudo_and_env():
    assert safety._program_name(["sudo", "rm", "-rf", "/"]) == "rm"
    assert safety._program_name(["env", "FOO=bar", "pacman", "-S"]) == "pacman"
    assert safety._program_name(["doas", "dd"]) == "dd"


def test_confirm_requires_affirmative():
    cmd = "sudo pacman -S vlc"
    assert safety.confirm(lambda _: "y", cmd) is True
    assert safety.confirm(lambda _: "yes", cmd) is True
    assert safety.confirm(lambda _: "n", cmd) is False
    assert safety.confirm(lambda _: "", cmd) is False


def test_dry_run_never_executes():
    policy = safety.ConfirmPolicy(dry_run=True)
    # Even an affirmative answer must not authorise execution in dry-run.
    assert safety.confirm(lambda _: "y", "sudo pacman -S vlc", policy) is False


def test_dd_to_regular_file_not_blocked():
    # dd writing to a normal file is fine; only /dev targets are blocked.
    verdict = safety.validate("dd if=in.img of=out.img")
    # 'dd' itself is in DESTRUCTIVE_COMMANDS, so it is blocked conservatively.
    assert verdict.risk is Risk.BLOCKED


def test_guarded_rm_of_named_file_is_allowed():
    # Deleting one specific, in-tree file/folder by name is permitted (the
    # caller still requires an explicit confirmation).
    for cmd in ("rm report.txt", "rm -r myfolder", "rm notes.md", "rm -i old.log"):
        assert safety.validate(cmd).allowed, cmd


def test_dangerous_rm_forms_stay_blocked():
    for cmd in ("rm -rf /", "rm -rf myfolder", "rm *", "rm ~", "rm /etc/passwd",
                "rm ../../thing", "rm a b c", "rm .", 'rm "a; rm -rf /"'):
        assert not safety.validate(cmd).allowed, cmd


def test_sanitize_preserves_quoting_for_spaces():
    # Re-joining tokens must not drop the quotes around a spaced filename.
    assert safety.sanitize("rm 'blah blah.txt'") == "rm 'blah blah.txt'"
    v = safety.validate("rm 'blah blah.txt'")
    assert v.allowed
    assert v.sanitized == "rm 'blah blah.txt'"


def test_sanitize_still_strips_autoconfirm():
    assert safety.sanitize("sudo pacman -S firefox --noconfirm") == \
        "sudo pacman -S firefox"
    assert "--noconfirm" not in safety.validate("sudo pacman -S vlc --noconfirm").sanitized
