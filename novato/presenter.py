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
        # Reserve space: index (6) + name (width) + separator (4) + repo (10) +
        # padding (4), plus the "✓ installed" tag when any result needs it.
        any_installed = any(rr.result.installed for rr in ranked)
        term_w = self.console.width or 100
        desc_max = max(20, term_w - width - 24 - (14 if any_installed else 0))
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
            if r.installed:
                line.append("  ✓ installed", style="bold green")
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

    # -- How-to answers (file/nav/process tasks) ----------------------------

    def show_howto(self, answer) -> None:
        """Render a one-line 'how do I ...' answer: the task, then the command.

        Deliberately minimal — one command, one explanation — so a beginner sees
        the answer, not a wall of options. A danger warning is shown for tasks
        that delete data; such answers are never offered for execution.
        """
        self.console.print()
        t = Text()
        t.append("To ", style="bold")
        t.append(answer.explanation, style="bold")
        t.append(":")
        self.console.print(t)
        cmd = Text("   ")
        cmd.append(answer.command, style="bold white on grey15")
        self.console.print(cmd)
        if answer.note:
            self.console.print(f"   [dim]{answer.note}[/]")
        if answer.dangerous:
            self.console.print("   [bold red]⚠ This permanently deletes data — "
                               "there is no undo.[/]")
        elif not answer.runnable and answer.placeholder:
            self.console.print("   [dim]Replace the example name(s) above with your "
                               "own, then run it.[/]")

    # -- Cheat sheets (/cheat) ----------------------------------------------

    def show_cheat(self, category: str, blurb: str, rows: Sequence[tuple[str, str]]) -> None:
        """Render a command cheat-sheet for one category as a clean table."""
        from rich.table import Table

        table = Table(
            title=f"📋 {category} — {blurb}",
            title_style="bold cyan",
            show_header=True,
            header_style="bold",
            expand=False,
            border_style="dim",
        )
        table.add_column("Command", style="bold white", no_wrap=True)
        table.add_column("What it does")
        for command, desc in rows:
            table.add_row(command, desc)
        self.console.print()
        self.console.print(table)

    def show_cheat_index(self, categories: Sequence[str]) -> None:
        """List the available cheat-sheet categories when none was given."""
        self.console.print()
        self.console.print("Pick a topic, e.g. [bold cyan]novato /cheat files[/]:")
        self.console.print("  " + "  ".join(f"[cyan]{c}[/]" for c in categories))

    # -- Disk report (/disk) ------------------------------------------------

    def show_disk(self, mounts, big_dirs, *, scanned_path: str = "",
                  suggest_ncdu: bool = False) -> None:
        """Render the disk-usage detective output: free space + space hogs."""
        from rich.table import Table

        self.console.print()
        if mounts:
            table = Table(title="💾 Disk space", title_style="bold cyan",
                          header_style="bold", border_style="dim", expand=False)
            table.add_column("Mounted on", style="bold")
            table.add_column("Size")
            table.add_column("Used")
            table.add_column("Free", style="green")
            table.add_column("Full")
            for m in mounts:
                pct_style = "red" if m.use_percent >= 90 else (
                    "yellow" if m.use_percent >= 75 else "green")
                table.add_row(m.mounted_on, m.size, m.used, m.avail,
                              f"[{pct_style}]{m.use_percent}%[/]")
            self.console.print(table)
        if big_dirs:
            where = f" in {scanned_path}" if scanned_path else ""
            self.console.print(f"\nBiggest folders{where}:")
            for d in big_dirs:
                self.console.print(f"  [bold]{d.size:>6}[/]  {d.path}")
        if suggest_ncdu:
            self.console.print("\n[dim]Tip: install [bold]ncdu[/] for an "
                               "interactive disk explorer — 'novato ncdu'.[/]")

    def show_storage_scan(self, scan, *, mounts=(), scanned_path: str = "",
                          suggest_ncdu: bool = False) -> None:
        """Render the deep scan while keeping personal data clearly separate."""
        from .storage import format_bytes

        self.show_disk(mounts, scan.large_dirs, scanned_path=scanned_path,
                       suggest_ncdu=suggest_ncdu)
        self.console.print(
            f"\nOn your home filesystem: [bold]{format_bytes(scan.free_bytes)} free[/] "
            f"of {format_bytes(scan.total_bytes)}."
        )
        if scan.cache_dirs:
            self.console.print("\nLargest app-cache areas (review only):")
            for entry in scan.cache_dirs:
                self.console.print(f"  [bold]{entry.size:>6}[/]  {entry.path}")
            self.console.print(
                "[dim]Caches can contain offline files or active app data, so Novato "
                "does not label every cache folder as safe to erase.[/]"
            )
        if scan.notes:
            self.console.print("\nWhat Novato understood:")
            for note in scan.notes:
                self.console.print(f"  • {note}")
        if scan.system_dirs:
            self.console.print("\nLargest system-managed areas (protected):")
            for entry in scan.system_dirs[:8]:
                self.console.print(f"  [bold]{entry.size:>6}[/]  {entry.path}")
            self.console.print(
                "[dim]These belong to Linux or installed applications. Size alone "
                "does not make them safe cleanup targets.[/]"
            )
        if scan.inventory is not None:
            self.show_storage_intelligence(scan.inventory)

    def show_storage_intelligence(self, inventory) -> None:
        """Render local evidence about importance, rebuildability, and duplicates."""
        from .storage import format_bytes

        labels = {
            "important": ("Likely important — protected", "green"),
            "rebuildable": ("Rebuildable data — cleanup candidate", "cyan"),
            "review": ("Needs your judgment", "yellow"),
        }
        self.console.print(
            f"\nSmart local assessment ({inventory.files_scanned:,} files and "
            f"{inventory.dirs_scanned:,} folders inspected):"
        )
        for kind in ("important", "rebuildable", "review"):
            rows = [finding for finding in inventory.findings if finding.kind == kind]
            if not rows:
                continue
            title, colour = labels[kind]
            self.console.print(f"\n[{colour}]{title}[/]:")
            for finding in self._distinct_storage_findings(rows, limit=6):
                self.console.print(
                    f"  [bold]{format_bytes(finding.size_bytes):>9}[/]  {finding.path}"
                )
                self.console.print(f"             [dim]{finding.reason}[/]")

        if inventory.largest_files:
            self.console.print("\nLargest individual files (never auto-deleted):")
            for finding in inventory.largest_files[:8]:
                self.console.print(
                    f"  [bold]{format_bytes(finding.size_bytes):>9}[/]  "
                    f"[{labels[finding.kind][1]}]{finding.kind}[/]  {finding.path}"
                )
        if inventory.duplicates:
            self.console.print("\nExact large duplicates (content hash verified):")
            for group in inventory.duplicates[:5]:
                self.console.print(
                    f"  [bold]{format_bytes(group.reclaimable_bytes)} possible[/] "
                    f"across {len(group.paths)} identical files"
                )
                for path in group.paths[:4]:
                    self.console.print(f"     {path}")
            self.console.print(
                "[dim]Duplicates may be intentional backups; Novato only reports them.[/]"
            )
        if inventory.incomplete:
            self.console.print(
                "\n[yellow]The inventory hit its safety/time limit. Results are useful "
                "but not a claim that every file was inspected.[/]"
            )

    @staticmethod
    def _distinct_storage_findings(rows, *, limit: int):
        """Prefer useful parent summaries over double-counted nested paths."""
        selected = []
        for finding in sorted(
            rows, key=lambda row: (len(row.path.rstrip("/").split("/")), -row.size_bytes),
        ):
            path = finding.path.rstrip("/")
            if any(path == parent or path.startswith(parent + "/")
                   for parent in (item.path.rstrip("/") for item in selected)):
                continue
            selected.append(finding)
        selected.sort(key=lambda row: row.size_bytes, reverse=True)
        return selected[:limit]

    def show_cleanup_item(self, item) -> None:
        """Explain one cleanup candidate and its measured upper-bound saving."""
        from .storage import format_bytes

        self.console.print()
        self.console.print(
            f"[bold cyan]{item.title}[/] — up to "
            f"[bold]{format_bytes(item.estimated_bytes)}[/]"
        )
        self.console.print(f"  {item.description}")

    def show_review_candidates(self, candidates) -> None:
        """Show the interactive folder/file drill-down menu."""
        from rich.table import Table
        from .storage import format_bytes

        table = Table(
            title="🔎 Inspect deeper — choose a folder or file",
            header_style="bold", border_style="dim", expand=False,
        )
        table.add_column("#", style="bold cyan", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Age")
        table.add_column("Type")
        table.add_column("Path", overflow="fold")
        for index, candidate in enumerate(candidates, start=1):
            age = f"~{candidate.age_days}d" if candidate.age_days is not None else "unknown"
            table.add_row(
                str(index), format_bytes(candidate.size_bytes), age,
                candidate.category, candidate.path,
            )
        self.console.print()
        self.console.print(table)

    def show_review_detail(self, candidate, children=()) -> None:
        """Explain why a selected path is present and show its next level."""
        from .storage import format_bytes

        self.console.print()
        self.console.print(f"[bold cyan]{candidate.title}[/]")
        self.console.print(f"  Path:   {candidate.path}")
        self.console.print(f"  Size:   {format_bytes(candidate.size_bytes)}")
        if candidate.age_days is not None:
            self.console.print(f"  Age:    newest content modified about {candidate.age_days} days ago")
        self.console.print(f"  Why:    {candidate.reason}")
        self.console.print(f"  Action: {candidate.action}")
        if children:
            self.console.print("\n  Inside this folder:")
            for child in children:
                self.console.print(f"    [bold]{child.size:>6}[/]  {child.path}")

    def show_storage_result(self, before, after) -> None:
        """Show actual reclaimed and remaining space after the verification scan."""
        from .storage import format_bytes

        before_fs = {entry.device: entry for entry in before.filesystems}
        changes = []
        for current in after.filesystems:
            previous = before_fs.get(current.device)
            if previous is None:
                continue
            changes.append((current, max(0, current.free_bytes - previous.free_bytes)))
        # Backward-compatible fallback for injected/older scan snapshots.
        recovered = sum(change for _, change in changes) if changes else max(
            0, after.free_bytes - before.free_bytes,
        )
        self.console.print()
        if recovered:
            self.success(f"Recovered {format_bytes(recovered)}.")
        else:
            self.warn("The commands finished, but no measurable space was recovered.")
        if len(changes) > 1:
            for capacity, change in changes:
                label = "Home (/home)" if capacity.path != "/" else "System (/)"
                self.console.print(
                    f"  {label}: +{format_bytes(change)}, "
                    f"{format_bytes(capacity.free_bytes)} free"
                )
        self.console.print(
            f"Free space now: [bold green]{format_bytes(after.free_bytes)}[/] "
            f"of {format_bytes(after.total_bytes)} on your home filesystem."
        )

    def show_space(self, scan, *, distro_name: str = "") -> None:
        """Give a direct capacity answer without entering the cleanup workflow."""
        from .storage import format_bytes

        where = f" on {distro_name}" if distro_name else ""
        self.console.print()
        self.console.print(f"💾 Storage{where}")
        self.console.print(f"  Available: [bold green]{format_bytes(scan.free_bytes)}[/]")
        self.console.print(f"  Used:      {format_bytes(scan.used_bytes)}")
        self.console.print(f"  Total:     {format_bytes(scan.total_bytes)}")
        self.console.print("\n[dim]To safely find cleanup options: novato clean storage safely[/]")

    # -- Process helper (/process) ------------------------------------------

    def show_processes(self, procs, *, title: str = "Running programs") -> None:
        """Render a numbered list of processes (for inspection or killing)."""
        from rich.table import Table

        self.console.print()
        table = Table(title=f"⚙ {title}", title_style="bold cyan",
                      header_style="bold", border_style="dim", expand=False)
        table.add_column("#", style="bold cyan")
        table.add_column("PID", style="bold")
        table.add_column("Name")
        table.add_column("Detail", style="dim")
        for i, p in enumerate(procs, start=1):
            table.add_row(str(i), str(p.pid), p.name or "(unknown)", p.detail)
        self.console.print(table)

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
