"""Focused tests for Presenter input contracts."""

from __future__ import annotations

import pytest
from rich.console import Console

from novato.presenter import Presenter


def _presenter(answers: list[str]):
    prompts: list[str] = []
    replies = iter(answers)

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    return Presenter(
        console=Console(file=None, no_color=True),
        input_fn=answer,
    ), prompts


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("1", [0]),
        ("1 3 5", [0, 2, 4]),
        ("1,3,5", [0, 2, 4]),
        ("1, 3  5", [0, 2, 4]),
        ("2-4", [1, 2, 3]),
        ("1, 3-5 7", [0, 2, 3, 4, 6]),
    ],
)
def test_prompt_choices_accepts_single_batch_and_range_entries(answer, expected):
    presenter, _ = _presenter([answer])

    assert presenter.prompt_choices(7) == expected


def test_prompt_choices_deduplicates_while_preserving_first_seen_order():
    presenter, _ = _presenter(["5 2-4,3,5 1"])

    assert presenter.prompt_choices(5) == [4, 1, 2, 3, 0]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("13 15 17", [12, 14, 16]),
        ("13,15,17", [12, 14, 16]),
        ("13-15", [12, 13, 14]),
    ],
)
def test_prompt_choices_accepts_storage_table_examples(answer, expected):
    presenter, _ = _presenter([answer])

    assert presenter.prompt_choices(30) == expected


@pytest.mark.parametrize("answer", ["", "q", "Q", "quit", "  QUIT  "])
def test_prompt_choices_quit_entries_return_none(answer):
    presenter, _ = _presenter([answer])

    assert presenter.prompt_choices(5) is None


def test_prompt_choices_eof_and_ctrl_c_return_none():
    def stop_with(error):
        def answer(_prompt):
            raise error

        return Presenter(input_fn=answer)

    assert stop_with(EOFError()).prompt_choices(5) is None
    assert stop_with(KeyboardInterrupt()).prompt_choices(5) is None


@pytest.mark.parametrize(
    "invalid",
    [
        "0",
        "6",
        "1 6",
        "4-2",
        "2-6",
        "1,,3",
        ",1",
        "1,",
        "1 two",
        "q 1",
        "1.5",
        "-1",
        "1 - 3",
    ],
)
def test_prompt_choices_rejects_entire_invalid_entry_then_reprompts(invalid):
    presenter, prompts = _presenter([invalid, "2 4"])

    assert presenter.prompt_choices(5) == [1, 3]
    assert len(prompts) == 2


def test_prompt_choices_with_no_available_rows_does_not_prompt():
    called = False

    def answer(_prompt):
        nonlocal called
        called = True
        return "1"

    presenter = Presenter(input_fn=answer)

    assert presenter.prompt_choices(0) is None
    assert called is False


def test_prompt_choice_keeps_its_single_choice_contract():
    presenter, prompts = _presenter(["1 2", "2"])

    assert presenter.prompt_choice(3) == 1
    assert len(prompts) == 2
