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
    # "" = start from the top at the lesson-index chooser, then the quiz answer.
    answers = iter(["", "yes"])  # single lesson -> no "next?" prompt
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
    # Start from the top, answer lesson 1, then decline "Ready for the next lesson?".
    answers = iter(["", "yes", "n"])
    t = learner.Tutorial(
        system=_system(pm="zypper"),
        presenter=Presenter(input_fn=lambda p: next(answers, "n")),
        input_fn=lambda p: next(answers, "n"),
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    assert cfgmod.load_config().learn_progress.get("universal") == 1


def test_typing_q_during_practice_quits_and_saves(isolated_home, monkeypatch):
    """Typing 'q' at a practice prompt leaves the tutorial; lesson not marked done."""
    lessons = (
        learner.Lesson(slug="a", title="t", concept=("c",), command="pwd",
                       command_note="n", practice_prompt="type pwd", expected="pwd"),
        learner.Lesson(slug="b", title="t", concept=("c",), command="ls",
                       command_note="n", practice_prompt="type ls", expected="ls"),
    )
    monkeypatch.setattr(learner, "UNIVERSAL", lessons)
    answers = iter(["", "q"])  # start from the top, then quit at the first practice
    t = learner.Tutorial(
        system=_system(pm="zypper"),
        presenter=Presenter(input_fn=lambda p: next(answers, "q")),
        input_fn=lambda p: next(answers, "q"),
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    # Quit before completing lesson 1 -> progress stays at 0, so /learn resumes there.
    assert cfgmod.load_config().learn_progress.get("universal", 0) == 0


def test_eof_during_practice_quits_without_flooding(isolated_home, monkeypatch):
    """EOF / Ctrl+C must end the tutorial, not loop through every lesson."""
    seen = {"prompts": 0}

    def feed(prompt):
        seen["prompts"] += 1
        if seen["prompts"] == 1:
            return ""  # the lesson-index chooser: start from the top
        raise EOFError  # then EOF at the first practice prompt

    lessons = tuple(
        learner.Lesson(slug=str(i), title="t", concept=("c",), command="pwd",
                       command_note="n", practice_prompt="type pwd", expected="pwd")
        for i in range(5)
    )
    monkeypatch.setattr(learner, "UNIVERSAL", lessons)
    t = learner.Tutorial(
        system=_system(pm="zypper"),
        presenter=Presenter(input_fn=feed),
        input_fn=feed,
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    # chooser (1) + first practice prompt that EOFs (2); must not flood all lessons.
    assert seen["prompts"] == 2


def test_choose_start_jumps_to_lesson_number(isolated_home, monkeypatch):
    """Typing a lesson number starts the track there, overriding saved progress."""
    lessons = tuple(
        learner.Lesson(slug=str(i), title=f"L{i}", concept=("c",), command="pwd",
                       command_note="n", quiz=("q?", "yes"))
        for i in range(5)
    )
    monkeypatch.setattr(learner, "UNIVERSAL", lessons)
    # Start at lesson 3, answer it, then decline to continue.
    answers = iter(["3", "yes", "n"])
    t = learner.Tutorial(
        system=_system(pm="zypper"),
        presenter=Presenter(input_fn=lambda p: next(answers, "n")),
        input_fn=lambda p: next(answers, "n"),
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    # Completed lesson 3 (index 2) -> progress saved as 3.
    assert cfgmod.load_config().learn_progress.get("universal") == 3


def test_choose_start_skip_jumps_to_distro_track(isolated_home, monkeypatch):
    """'skip' bypasses the universal basics and goes to the system-specific track."""
    universal = tuple(
        learner.Lesson(slug=f"u{i}", title=f"U{i}", concept=("c",), command="pwd",
                       command_note="n", quiz=("q?", "yes"))
        for i in range(3)
    )
    monkeypatch.setattr(learner, "UNIVERSAL", universal)
    # 'skip' -> distro track, then 'yes' to start it, answer its first lesson,
    # decline the rest.
    answers = iter(["skip", "yes", "yes", "n"])
    t = learner.Tutorial(
        system=_system(pm="pacman", distro="arch"),  # has a distro track
        presenter=Presenter(input_fn=lambda p: next(answers, "n")),
        input_fn=lambda p: next(answers, "n"),
        config=cfgmod.Config(),
    )
    assert t.run() == 0
    # Universal basics were skipped -> no universal progress recorded.
    assert cfgmod.load_config().learn_progress.get("universal", 0) == 0
    # But the distro (arch) track advanced.
    assert cfgmod.load_config().learn_progress.get("arch", 0) >= 1
