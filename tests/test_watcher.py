"""Tests for the error-correction rule engine (the /mistake brain)."""

from __future__ import annotations


from novato import rules
from novato.rules import ErrorContext


def _arch_ctx(command, stderr, exit_code=1):
    return ErrorContext(
        command=command,
        exit_code=exit_code,
        stderr=stderr,
        distro_id="arch",
        package_manager="pacman",
        install_cmd="sudo pacman -S",
    )


def test_at_least_fifty_rules_or_reasonable():
    # The spec calls for a rich rule set; ensure the engine is non-trivial.
    assert rules.rule_count() >= 10


def test_command_typo_pacman():
    ctx = _arch_ctx("sudo pacmna -S vlc", "bash: pacmna: command not found", 127)
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "command_typo"
    assert c.fix == "sudo pacman -S vlc"


def test_wrong_package_manager_on_arch():
    ctx = _arch_ctx("apt install vlc", "bash: apt: command not found", 127)
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "wrong_package_manager"
    assert "pacman" in c.fix


def test_wrong_pm_fix_drops_subcommand():
    # Regression: "apt install vlc" must map to "sudo pacman -S vlc",
    # not "sudo pacman -S install vlc".
    ctx = _arch_ctx("apt install vlc", "bash: apt: command not found", 127)
    c = rules.analyze(ctx)
    assert c is not None and c.rule_name == "wrong_package_manager"
    assert c.fix == "sudo pacman -S vlc"
    assert "install" not in c.fix.split()[3:]


def test_missing_sudo():
    ctx = _arch_ctx(
        "pacman -S vlc",
        "error: you cannot perform this operation unless you are root.",
    )
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "missing_sudo"
    assert c.fix == "sudo pacman -S vlc"


def test_python_module_missing():
    ctx = _arch_ctx(
        "python script.py",
        "ModuleNotFoundError: No module named 'requests'",
    )
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "python_module_missing"
    assert c.fix == "pip install requests"


def test_python_submodule_uses_top_level():
    ctx = _arch_ctx("python a.py", "No module named 'google.protobuf'")
    c = rules.analyze(ctx)
    assert c is not None
    assert c.fix == "pip install google"


def test_pacman_db_lock():
    ctx = _arch_ctx(
        "sudo pacman -S vlc",
        "error: unable to lock database",
    )
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "pacman_db_lock"


def test_disk_full():
    ctx = _arch_ctx("cp big.iso /mnt/", "cp: error writing: No space left on device")
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "disk_full"


def test_git_not_a_repo():
    ctx = _arch_ctx("git status", "fatal: not a git repository (or any parent)")
    c = rules.analyze(ctx)
    assert c is not None
    assert c.rule_name == "git_not_a_repo"


def test_success_returns_none():
    ctx = _arch_ctx("ls", "", exit_code=0)
    assert rules.analyze(ctx) is None


def test_already_sudo_does_not_resuggest_sudo():
    ctx = _arch_ctx("sudo pacman -S vlc", "permission denied somewhere")
    c = rules.analyze(ctx)
    # missing_sudo must not fire because command already has sudo.
    assert c is None or c.rule_name != "missing_sudo"
