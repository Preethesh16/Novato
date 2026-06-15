"""Tests for the interactive /learn tutorial."""

from __future__ import annotations

import pytest

from novato import config as cfgmod
from novato import learner
from novato.detector import SystemInfo
from novato.presenter import Presenter


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    yield tmp_path


def _system(pm="pacman", distro="arch"):
    return SystemInfo(
        distro_id=distro, distro_name=distro.title(), distro_version="",
        package_manager=pm, install_cmd=f"sudo {pm} -S", search_cmd="",
        supports_aur=(pm == "pacman"), aur_helper=None, shell="bash",
        supported=True,
    )


@pytest.mark.parametrize("pm,expected", [
    ("apt", "ubuntu"),
    ("pacman", "arch"),
    ("dnf", "fedora"),
    ("zypper", None),
    ("unknown", None),
])
def test_package_for_system(pm, expected):
    assert learner.package_for_system(_system(pm=pm)) == expected


def test_matches_is_lenient_on_first_token():
    assert learner._matches("ls -la", "ls -la") is True
    assert learner._matches("ls -la", "ls") is True       # forgiving
    assert learner._matches("pwd", "pwd") is True
    assert learner._matches("pwd", "cd") is False
    assert learner._matches("pwd", "") is False


def test_quiz_accepts_correct_answer_and_advances(isolated_home, monkeypatch):
    # Drive a single quiz lesson: answer the comprehension question correctly,
    # then decline to continue so the run stops cleanly.
    lesson = learner.Lesson(
        slug="q", title="t", concept=("c",), command="x", command_note="n",
        quiz=("question?", "yes"),
    )
    monkeypatch.setattr(learner, "UNIVERSAL", (lesson,))
    answers = iter(["yes"])  # quiz answer; single lesson -> no "next?" prompt
    t = learner.Tutorial(
        system=_system(pm="zypper"),  # no distro package -> finishes after track
        presenter=Presenter(input_fn=lambda p: next(answers, "n")),
        input_fn=lambda p: next(answers, "n"),
        config=cfgmod.Config(),
    )
    rc = t.run()
    assert rc == 0
    # Progress for the universal track was saved (1 lesson completed).
    assert cfgmod.load_config().learn_progress.get("universal") == 1


def test_practice_runs_demo_via_injected_runner(isolated_home, monkeypatch):
    lesson = learner.Lesson(
        slug="p", title="t", concept=("c",), command="pwd", command_note="n",
        practice_prompt="type pwd", expected="pwd", run_demo=True,
    )
    monkeypatch.setattr(learner, "UNIVERSAL", (lesson,))
    ran = {}
    t = learner.Tutorial(
        system=_system(pm="zypper"),
        presenter=Presenter(input_fn=lambda p: "pwd"),
        input_fn=lambda p: "pwd",
        run_fn=lambda cmd: ran.setdefault("cmd", cmd) or "/home/u",
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    assert ran["cmd"] == "pwd"  # demo executed the vetted command, not raw input


def test_stop_midway_saves_progress(isolated_home, monkeypatch):
    lessons = (
        learner.Lesson(slug="a", title="t", concept=("c",), command="pwd",
                       command_note="n", quiz=("q?", "yes")),
        learner.Lesson(slug="b", title="t", concept=("c",), command="ls",
                       command_note="n", quiz=("q?", "yes")),
    )
    monkeypatch.setattr(learner, "UNIVERSAL", lessons)
    # Answer lesson 1 correctly, then decline "Ready for the next lesson?".
    answers = iter(["yes", "n"])
    t = learner.Tutorial(
        system=_system(pm="zypper"),
        presenter=Presenter(input_fn=lambda p: next(answers, "n")),
        input_fn=lambda p: next(answers, "n"),
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    assert cfgmod.load_config().learn_progress.get("universal") == 1
