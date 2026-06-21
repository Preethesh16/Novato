"""Tests for the task -> command knowledge base (howto)."""

from __future__ import annotations

import pytest

from novato import howto


def test_resolves_common_task_and_fills_argument():
    a = howto.resolve("unzip messi file")
    assert a is not None
    assert a.command == "unzip messi.zip"
    assert a.runnable is True
    assert a.dangerous is False


def test_bare_task_is_reference_only():
    # No concrete filename -> show a placeholder, don't offer to run it.
    a = howto.resolve("unzip the file")
    assert a is not None
    assert a.command == "unzip filename.zip"
    assert a.runnable is False


def test_bare_delete_with_no_name_is_reference_only():
    # Without a concrete filename we only show `rm filename.txt`, never run it.
    a = howto.resolve("delete a file")
    assert a is not None
    assert a.dangerous is True
    assert a.runnable is False
    assert a.placeholder is True


def test_delete_with_real_filename_is_runnable():
    # Given a concrete name, the delete becomes runnable (still gated by the
    # safety layer and a default-No confirm in the caller). The file-vs-folder
    # choice is settled at the app layer; here we just check the name survives.
    a = howto.resolve("delete report.txt", threshold=0.2)
    assert a is not None
    assert a.command.endswith("report.txt")   # real name, extension preserved
    assert a.dangerous is True
    assert a.runnable is True
    assert a.placeholder is False


def test_extract_arg_preserves_extension_and_dedups():
    # No double extension when the template already appends one.
    a = howto.resolve("unzip report.zip", threshold=0.2)
    assert a is not None
    assert a.command == "unzip report.zip"


def test_multi_argument_task_is_reference_only():
    a = howto.resolve("rename a file")
    assert a is not None
    assert a.runnable is False  # rename needs two names; show, don't run


def test_static_command_is_runnable():
    a = howto.resolve("where am i")
    assert a is not None
    assert a.command == "pwd"
    assert a.runnable is True


def test_update_system_uses_sentinel():
    a = howto.resolve("update my system")
    assert a is not None
    assert a.command == howto.SYNC_SENTINEL


@pytest.mark.parametrize("query", [
    "i want to edit videos",
    "web browser",
    "music player",
    "firefox",
    "password manager",
    "a private browser",
])
def test_package_requests_do_not_hijack_at_nlpm_threshold(query):
    # Genuine package intents must score below the natural-language threshold,
    # so run_query falls through to the package search instead.
    assert howto.resolve(query, threshold=0.72) is None


def test_no_match_returns_none():
    assert howto.resolve("zxcvbnm qwerty", threshold=0.72) is None
    assert howto.resolve("", threshold=0.1) is None


def test_all_tasks_are_lowercase_and_unique():
    tasks = howto.all_tasks()
    assert tasks == sorted(tasks)
    assert len(tasks) == len(set(tasks))
    assert all(t == t.lower() for t in tasks)


def test_argument_extraction_skips_filler_words():
    a = howto.resolve("create a folder called projects")
    assert a is not None
    assert a.command == "mkdir projects"
