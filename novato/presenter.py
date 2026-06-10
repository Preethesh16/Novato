# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminal UI layer — all user-facing output, built on :mod:`rich`.

The presenter owns *every* pixel Novato prints: the status badge, search-result
lists, confirmation prompts, error panels, and `/explain` blocks. Keeping I/O
here (and nowhere else) makes the rest of Novato pure and testable.

Design choices:
* A single :class:`Presenter` wraps a ``rich`` ``Console`` plus an injectable
  input function, so prompts can be driven by tests without a real TTY.
* Every status line starts with a mode badge, e.g. ``[Novato • Basic ⚡]``.
* No business logic lives here — the presenter never decides *what* to do, only
  how to show it.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .ranker import RankedResult

# Mode -> (label, emoji, rich colour). Mirrors the spec's status indicators.
_MODE_BADGE = {
    "basic":   ("Basic", "⚡", "cyan"),
    "offline": ("Offline", "🔒", "green"),
    "online":  ("Groq", "⚡", "magenta"),
    "both":    ("Both", "⭐", "yellow"),
}

_DIVIDER = "━" * 38


class Presenter:
    """Renders Novato output and collects user input."""

    def __init__(
        self,
        console: Optional[Console] = None,
        input_fn: Callable[[str], str] = input,
        *,
        no_color: bool = False,
    ) -> None:
        self.console = console or Console(no_color=no_color, highlight=False)
        self._input = input_fn

    # -- Status badge -------------------------------------------------------

    def badge(self, mode: str) -> Text:
        """Return the ``[Novato • <Mode> <emoji>]`` badge as rich Text."""
        label, emoji, color = _MODE_BADGE.get(mode, _MODE_BADGE["basic"])
        t = Text()
        t.append("[Novato • ", style="dim")
        t.append(f"{label} {emoji}", style=f"bold {color}")
        t.append("]", style="dim")
        return t

    def status_line(self, mode: str, message: str) -> None:
        """Print a badged status line, e.g. 'Searching repositories...'."""
        line = self.badge(mode)
        line.append(" " + message)
        self.console.print(line)

    # -- Search results -----------------------------------------------------

    def show_results(
        self,
        ranked: Sequence[RankedResult],
        *,
        distro_name: str = "",
        describe: Callable[[str], str] | None = None,
    ) -> None:
        """Print the numbered, beginner-friendly list of package options."""
        where = f" for your system ({distro_name})" if distro_name else ""
        self.console.print()
        self.console.print(f"Found {len(ranked)} option(s){where}:\n")
        width = max((len(rr.result.name) for rr in ranked), default=0)
        # Reserve space: index (6) + name (width) + separator (4) + repo (10) + padding (4)
        term_w = self.console.width or 100
        desc_max = max(20, term_w - width - 24)
        for i, rr in enumerate(ranked, start=1):
            r = rr.result
            desc = r.description or (describe(r.name) if describe else "") or ""
            if len(desc) > desc_max:
                desc = desc[:desc_max - 1] + "…"
            repo = f"({r.repo})" if r.repo else ""
            name = f"{r.name:<{width}}"
            line = Text(no_wrap=True, overflow="ellipsis")
            line.append(f"  [{i}] ", style="bold cyan")
            line.append(name, style="bold")
            if desc:
                line.append(f"  — {desc}")
            if repo:
                line.append(f"  {repo}", style="dim")
            self.console.print(line, no_wrap=True)
        self.console.print()

    def _ask(self, prompt: str) -> Optional[str]:
        """Read one line of input, returning None on EOF (no TTY / closed pipe)."""
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None

    def prompt_choice(self, count: int) -> Optional[int]:
        """Ask the user to pick 1..count. Returns a 0-based index or None (quit)."""
        while True:
            answer = self._ask(f"Pick [1-{count}] or 'q' to quit: ")
            if answer is None:
                return None
            raw = answer.strip().lower()
            if raw in ("q", "quit", ""):
                return None
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= count:
                    return n - 1
            self.console.print("[yellow]Please enter a number in range, or 'q'.[/]")

    # -- Command + confirmation --------------------------------------------

    def show_command(self, command: str) -> None:
        """Show the exact command that will run (always, before execution)."""
        t = Text("📋 Will run: ", style="bold")
        t.append(command, style="bold white on grey15")
        self.console.print(t)

    def confirm(self, command: str, *, default_no: bool = True) -> bool:
        """Prompt y/N for a command. Defaults to *no* (safety-first)."""
        suffix = "[y/N]" if default_no else "[Y/n]"
        answer = self._ask(f"Confirm? {suffix}: ")
        if answer is None:
            return False  # No input available -> safest choice is "no".
        raw = answer.strip().lower()
        if not raw:
            return not default_no
        return raw in ("y", "yes")

    def ask_yes_no(self, question: str, *, default_no: bool = True) -> bool:
        """Ask a free-form yes/no question. ``default_no`` sets the Enter default."""
        suffix = "[y/N]" if default_no else "[Y/n]"
        answer = self._ask(f"{question} {suffix}: ")
        if answer is None:
            return not default_no  # No TTY -> take the stated default.
        raw = answer.strip().lower()
        if not raw:
            return not default_no
        return raw in ("y", "yes")

    # -- Error correction (/mistake) ---------------------------------------

    def show_correction(self, correction) -> None:
        """Render a /mistake diagnosis panel."""
        body = Text()
        body.append("  Error:   ", style="bold red")
        body.append(correction.title + "\n")
        body.append("  Reason:  ", style="bold")
        body.append(correction.reason + "\n")
        if correction.fix:
            body.append("  Fix:     ", style="bold green")
            body.append(correction.fix)
        self.console.print(Panel(
            body,
            title="🔍 Novato caught an error",
            border_style="red",
            expand=False,
        ))

    # -- Teaching (/explain) ------------------------------------------------

    def show_explanation(self, parts: dict[str, str]) -> None:
        """Render an /explain block: token -> plain-English meaning."""
        if not parts:
            return
        body = Text()
        width = max(len(k) for k in parts)
        for token, meaning in parts.items():
            body.append(f"   {token:<{width}} ", style="bold cyan")
            body.append(f"= {meaning}\n")
        self.console.print(Panel(
            body, title="💡 Explain mode", border_style="cyan", expand=False,
        ))

    # -- Generic helpers ----------------------------------------------------

    def info(self, message: str) -> None:
        self.console.print(message)

    def success(self, message: str) -> None:
        self.console.print(f"[bold green]✅ {message}[/]")

    def warn(self, message: str) -> None:
        self.console.print(f"[bold yellow]⚠ {message}[/]")

    def error(self, message: str) -> None:
        self.console.print(f"[bold red]✖ {message}[/]")

    def blank(self) -> None:
        self.console.print()
