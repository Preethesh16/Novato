# SPDX-License-Identifier: GPL-3.0-or-later
"""Novato CLI entry point.

Wires the whole pipeline together and routes input. Novato accepts three shapes
of invocation:

* ``novato "i want to edit videos"``  — natural-language install flow (NLPM).
* ``novato /status`` / ``/help`` / ``/explain on`` / ...  — slash commands.
* ``novato --analyze-error "<cmd>" <exit_code>``  — called by the shell hook
  (the ``/mistake`` watcher) after a failed command.

We hand-roll argument handling (argparse for flags + a free-form remainder)
rather than using click subcommands, because the primary interface is free text
and ``/slash`` tokens, which don't map cleanly onto subcommands.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from . import __version__
from . import cheat as _cheat
from . import config as _config
from . import howto as _howto
from . import installed as _installed
from . import logger as _logger
from . import rules as _rules
from . import safety as _safety
from . import switcher as _switcher
from . import sysinfo as _sysinfo
from . import watcher as _watcher
from .detector import SystemInfo, detect_system
from .executor import execute
from .intent import IntentResolver
from .presenter import Presenter
from .ranker import rank
from .searcher import search_candidates
from .teacher import Teacher

# Natural-language phrases that should open the rich disk report rather than be
# treated as a package request.
_DISK_FULL_HINTS = (
    "disk full", "disk is full", "out of space", "running out of space",
    "no space left", "free up space", "taking up space", "taking space",
    "what's taking", "what is taking", "low on space", "storage full",
)

# Phrases that introduce an "...except these" clause in a system-update request,
# e.g. "update everything without touching android studio". Longest first so a
# two-word marker is matched before a substring of it.
_EXCLUDE_MARKERS = (
    "without updating", "without upgrading", "without touching", "apart from",
    "other than", "but not", "leave out", "leaving out", "don't update",
    "dont update", "do not update", "don't upgrade", "dont upgrade",
    "not update", "without", "except", "excluding", "ignoring", "ignore",
    "skipping", "skip", "besides",
)

# Verbs that signal the user wants to *uninstall* a package, not install one.
# "remove a file"/"delete a folder" are caught earlier by the how-to layer, so
# by the time we check these the target is a package name.
_REMOVE_VERBS = ("uninstall", "remove", "get rid of", "getting rid of",
                 "purge", "delete")
# Tokens to strip when isolating the package name from a removal request.
_REMOVE_NOISE = frozenset({
    "uninstall", "remove", "removing", "get", "getting", "rid", "of", "purge",
    "delete", "deleting", "the", "this", "that", "my", "please", "app",
    "application", "program", "package", "software",
    "file", "files", "folder", "folders", "directory", "directories",
})

# Words that carry no package-matching signal, so they're dropped when turning an
# exclusion clause into keywords to match against installed packages.
_EXCLUDE_NOISE = frozenset({
    "updating", "update", "upgrading", "upgrade", "updates", "any", "all",
    "other", "others", "related", "stuff", "things", "thing", "dev",
    "anything", "everything", "package", "packages", "app", "apps",
    "application", "applications", "system", "please", "also", "the", "and",
    "for", "with", "that", "this", "them", "those", "these", "are", "from",
    "touching", "touch", "keep", "keeping",
})


class App:
    """Holds shared state (system, config, UI) and implements the commands."""

    def __init__(
        self,
        *,
        system: Optional[SystemInfo] = None,
        config: Optional[_config.Config] = None,
        presenter: Optional[Presenter] = None,
        resolver: Optional[IntentResolver] = None,
        dry_run: bool = False,
    ) -> None:
        self.system = system or detect_system()
        self.config = config or _config.load_config()
        self.ui = presenter or Presenter()
        # Build the intent resolver around the configured AI tier (with the
        # fallback chain). Callers may inject a resolver directly for tests.
        if resolver is not None:
            self.resolver = resolver
        else:
            from .backends.router import build_router
            self.resolver = IntentResolver(build_router(self.config))
        self.teacher = Teacher()
        self.dry_run = dry_run

    # -- NLPM: natural-language install flow --------------------------------

    def run_query(self, query: str) -> int:
        """Resolve an intent, search repos, present options, install one.

        Before treating the query as a package request, we check whether it's
        actually a *task* the user wants to do in the terminal ("unzip this",
        "why is my disk full", "what's using port 8080"). Those are answered
        directly — Novato is a terminal companion, not just an installer.
        """
        handled = self._try_task(query)
        if handled is not None:
            return handled

        # "remove firefox" / "uninstall vlc" -> the removal flow, not a search
        # that would offer to *install* the very thing they want gone.
        removal = self._try_remove(query)
        if removal is not None:
            return removal

        if not self.system.supported:
            self.ui.error(
                f"Your distro ({self.system.distro_name}) isn't supported yet. "
                "Novato needs a known package manager."
            )
            return 2

        mode = self.config.mode
        self.ui.status_line(mode, "Searching repositories...")

        plan = self.resolver.resolve(query)
        candidates = list(plan.candidates) if plan.understood else []

        # If intent mapping found nothing (e.g. AI tier unreachable, or the
        # query is a literal package name like "firefox"), fall back to a
        # direct repo search on the meaningful words. This guarantees real
        # package names always work, even in pure Basic mode offline.
        if not candidates:
            terms = self._meaningful_terms(query)
            if not terms:
                self.ui.warn(
                    f"I couldn't map \"{query}\" to packages yet. Try simpler "
                    "words (e.g. \"video editor\"), or enable an AI mode with /switch."
                )
                return 1
            candidates = terms

        _logger.log_event(_logger.EVENT_SEARCH, query, note=plan.matched_intent)

        results = search_candidates(
            candidates,
            self.system.package_manager,
            include_aur=self.system.supports_aur,
        )
        # Fall back to offline descriptions if live search returned nothing
        # (e.g. no network / inside a sandbox): present the curated candidates.
        if not results:
            results = self._offline_candidates(candidates)
        if not results:
            self.ui.warn("No matching packages found in your repositories.")
            return 1

        # Mark packages that are already on this system so the list (and the
        # install step) can say "installed" instead of offering a blind reinstall.
        local = _installed.installed_versions(self.system.package_manager)
        for r in results:
            if r.name in local:
                r.installed = True
                r.version = r.version or local[r.name]

        ranked = rank(
            results, query=query, preferred_order=candidates, limit=8
        )
        self.ui.show_results(
            ranked,
            distro_name=self.system.distro_name,
            describe=self.resolver._backend.describe
            if hasattr(self.resolver._backend, "describe") else None,
        )

        idx = self.ui.prompt_choice(len(ranked))
        if idx is None:
            self.ui.info("Okay — nothing installed.")
            return 0

        chosen = ranked[idx].result
        return self._install(chosen.name, source=chosen.source)

    # -- Task helper: "how do I ...", disk, processes -----------------------

    def _try_task(self, query: str) -> Optional[int]:
        """Handle a query that's a *task* rather than a package request.

        Returns an exit code if handled, or ``None`` to fall through to the
        normal package-search flow.
        """
        lower = query.lower()

        # "why is my disk full" and friends -> the rich disk report.
        if any(hint in lower for hint in _DISK_FULL_HINTS):
            return self._cmd_disk()

        # "what's using port 8080" -> the process/port helper.
        if "port" in lower and _sysinfo.extract_port(query) is not None:
            return self._cmd_process(query)

        # Single-command tasks ("unzip this", "rename a file"). A high threshold
        # keeps genuine package requests ("video editor") out of this path.
        answer = _howto.resolve(query, threshold=0.72)
        if answer is not None:
            return self._present_howto(answer, offer_run=True, query=query)
        return None

    # -- Package removal: "uninstall firefox" -------------------------------

    def _try_remove(self, query: str) -> Optional[int]:
        """Handle "remove/uninstall <package>". Returns an exit code, or None.

        File/folder deletion ("remove a file") is handled earlier by the how-to
        layer, so any removal verb that reaches here targets a package.
        """
        lower = query.lower()
        if not any(verb in lower for verb in _REMOVE_VERBS):
            return None
        terms = [t for t in self._meaningful_terms(query)
                 if t not in _REMOVE_NOISE]
        if not terms:
            return None
        return self._cmd_remove(terms)

    def _cmd_remove(self, terms: list[str]) -> int:
        """Find the installed package(s) matching ``terms`` and offer to remove."""
        pm = self.system.package_manager
        installed = _installed.installed_versions(pm)

        # Prefer an exact package-name match ("firefox"); otherwise any installed
        # package whose name contains every term ("visual studio code" ->
        # visual-studio-code-bin).
        joined = "-".join(terms)
        squashed = "".join(terms)
        exact = [n for n in installed if n.lower() in (joined, squashed)]
        if exact:
            matches = sorted(exact)
        else:
            matches = sorted(n for n in installed
                             if all(t in n.lower() for t in terms))

        if not matches:
            self.ui.blank()
            self.ui.info(
                f"\"{' '.join(terms)}\" doesn't look installed, so there's "
                "nothing to remove."
            )
            return 0

        if len(matches) == 1:
            package = matches[0]
        else:
            self.ui.blank()
            self.ui.info("A few installed packages match — which one?")
            for i, name in enumerate(matches, 1):
                self.ui.info(f"  [bold cyan]{i}[/] {name}  ({installed[name]})")
            idx = self.ui.prompt_choice(len(matches))
            if idx is None:
                self.ui.info("Okay — nothing removed.")
                return 0
            package = matches[idx]

        command = self._remove_command(package)
        verdict = _safety.validate(command)
        if not verdict.allowed:
            self.ui.error(verdict.reason)
            return 2
        command = verdict.sanitized or command

        self.ui.blank()
        self.ui.info(f"[bold]{package}[/] is installed (version {installed[package]}).")
        self.ui.show_command(command)

        if self.dry_run:
            self.ui.info("[dim](dry-run: nothing was removed)[/]")
            return 0
        if not self.ui.confirm(command):
            _logger.log_event(_logger.EVENT_DECLINE, command)
            self.ui.info("Okay — left it installed.")
            return 0
        self.ui.blank()
        self.ui.status_line(self.config.mode, f"Removing {package}...")
        result = execute(command, on_line=lambda ln: self.ui.console.print(ln, markup=False))
        if result.succeeded:
            self.ui.success(f"Removed {package}.")
            return 0
        if result.exit_code >= 128:
            self.ui.info("Cancelled — nothing was changed.")
            return result.exit_code
        self.ui.error(f"Removal exited with code {result.exit_code}.")
        return result.exit_code

    def _remove_command(self, package: str) -> str:
        """The right 'uninstall this package' command for the current distro."""
        pm = self.system.package_manager
        return {
            "pacman": f"sudo pacman -Rs {package}",
            "apt": f"sudo apt remove {package}",
            "dnf": f"sudo dnf remove {package}",
            "zypper": f"sudo zypper remove {package}",
        }.get(pm, f"sudo {pm} remove {package}")

    def _present_howto(self, answer, *, offer_run: bool, query: str = "") -> int:
        """Show a how-to answer and, when safe, offer to run it."""
        if answer.command == _howto.SYNC_SENTINEL:
            ignore = self._update_exclusions(query)
            answer.command = self._system_update_command(ignore=ignore)
            answer.runnable = False  # whole-system updates: show, let them run it
            if ignore:
                answer.note = ("Skipping: " + ", ".join(ignore)
                               + " — they won't be upgraded.")
            elif self._asked_to_exclude(query):
                # They asked to exclude something, but nothing installed matched.
                answer.note = ("Nothing your package manager installed matches "
                               "what you asked to skip, so a normal update won't "
                               "touch it anyway.")

        self.ui.show_howto(answer)

        if not offer_run or not answer.runnable or answer.dangerous:
            return 0

        command = answer.command
        verdict = _safety.validate(command)
        if not verdict.allowed:
            return 0  # already shown for reference; safety won't run it
        command = verdict.sanitized or command

        if self.dry_run:
            self.ui.info("[dim](dry-run: nothing was executed)[/]")
            return 0
        self.ui.blank()
        if not self.ui.confirm(command):
            self.ui.info("Okay — didn't run it.")
            return 0
        result = execute(command, on_line=lambda ln: self.ui.console.print(ln, markup=False))
        return result.exit_code if result.executed else 0

    def _system_update_command(self, *, ignore: Optional[list[str]] = None) -> str:
        """The right 'update everything' command for this distro (for display).

        When ``ignore`` lists packages, build the distro-specific 'hold these
        back' variant so the user can update the rest of the system while
        leaving named packages (e.g. ``android-studio``) at their current
        version.
        """
        pm = self.system.package_manager
        ig = ignore or []
        if pm == "pacman":
            base = "sudo pacman -Syu"
            return base + (" --ignore=" + ",".join(ig) if ig else "")
        if pm == "apt":
            if ig:
                held = " ".join(ig)
                return (f"sudo apt-mark hold {held} && sudo apt update && "
                        f"sudo apt upgrade && sudo apt-mark unhold {held}")
            return "sudo apt update && sudo apt upgrade"
        if pm == "dnf":
            base = "sudo dnf upgrade"
            return base + (" --exclude=" + ",".join(ig) if ig else "")
        if pm == "zypper":
            if ig:
                locks = " ".join(ig)
                return (f"sudo zypper addlock {locks} && sudo zypper update && "
                        f"sudo zypper removelock {locks}")
            return "sudo zypper update"
        return self.system.sync_cmd or "your package manager's update command"

    def _asked_to_exclude(self, query: str) -> bool:
        """True if the query contains an 'except <something>' clause."""
        lower = query.lower()
        return any(marker in lower for marker in _EXCLUDE_MARKERS)

    def _exclude_phrases(self, query: str) -> list[list[str]]:
        """Break an update query's exclusion clause into product phrases.

        Each "or"/"and"/comma-separated chunk becomes one phrase (a list of its
        significant tokens), so "android studio or chrome" -> [['android',
        'studio'], ['chrome']]. A package later has to match *every* token of a
        phrase, which keeps "android studio" from also catching
        "visual-studio-code" off the lone word "studio". Returns [] when there's
        no exclusion clause.
        """
        import re

        lower = query.lower()
        cut = -1
        for marker in _EXCLUDE_MARKERS:
            pos = lower.find(marker)
            if pos != -1:
                end = pos + len(marker)
                cut = end if cut == -1 else min(cut, end)
        if cut == -1:
            return []

        phrases: list[list[str]] = []
        for chunk in re.split(r"\bor\b|\band\b|\bplus\b|,", lower[cut:]):
            chunk = re.sub(r"[^a-z0-9\s]", " ", chunk)
            toks = [w for w in chunk.split()
                    if len(w) >= 3 and w not in _EXCLUDE_NOISE]
            if toks and toks not in phrases:
                phrases.append(toks)
        return phrases

    def _update_exclusions(self, query: str) -> list[str]:
        """Resolve an update query's exclusion clause to real installed packages.

        Matches each requested product phrase against the names of packages this
        system actually has installed, so the ``--ignore`` list names real
        packages rather than guesses. Returns a sorted, de-duplicated list
        (possibly empty).
        """
        phrases = self._exclude_phrases(query)
        if not phrases:
            return []
        installed = _installed.installed_versions(self.system.package_manager)
        hits = set()
        for name in installed:
            low = name.lower()
            if any(all(tok in low for tok in phrase) for phrase in phrases):
                hits.add(name)
        return sorted(hits)

    def _cmd_cheat(self, arg: str) -> int:
        """Show a command cheat-sheet, or the list of topics."""
        if not arg:
            self.ui.show_cheat_index(_cheat.categories())
            return 0
        category = _cheat.resolve_category(arg)
        if category is None:
            self.ui.warn(f"No cheat-sheet called '{arg}'.")
            self.ui.show_cheat_index(_cheat.categories())
            return 1
        self.ui.show_cheat(category, _cheat.CATEGORY_BLURBS.get(category, ""),
                           _cheat.get(category))
        return 0

    def _cmd_man(self, task: str) -> int:
        """Translate a *task* into the single command that does it (no execution)."""
        task = task.strip().strip('"').strip("'")
        if not task:
            self.ui.info('Tell me the task, e.g.  novato /man "unzip a file"')
            return 1
        answer = _howto.resolve(task, threshold=0.45)
        if answer is None:
            self.ui.warn(f"I don't have a one-liner for \"{task}\" yet.")
            self.ui.info("Try [bold]/cheat[/] for a topic list, or describe it differently.")
            return 1
        if answer.command == _howto.SYNC_SENTINEL:
            ignore = self._update_exclusions(task)
            answer.command = self._system_update_command(ignore=ignore)
            if ignore:
                answer.note = ("Skipping: " + ", ".join(ignore)
                               + " — they won't be upgraded.")
        self.ui.show_howto(answer)
        return 0

    def _cmd_do(self, task: str) -> int:
        """Explicit entry point for a terminal task; offers to run it."""
        task = task.strip().strip('"').strip("'")
        if not task:
            self.ui.info('Tell me what to do, e.g.  novato /do "rename a file"')
            return 1
        answer = _howto.resolve(task, threshold=0.45)
        if answer is None:
            self.ui.warn(f"I'm not sure how to do \"{task}\" yet.")
            self.ui.info("Try [bold]/cheat[/] for common commands.")
            return 1
        return self._present_howto(answer, offer_run=True, query=task)

    def _cmd_disk(self) -> int:
        """Disk-space detective: free space plus the biggest folders."""
        home = os.path.expanduser("~")
        mounts = _sysinfo.disk_mounts()
        big = _sysinfo.largest_dirs(home, limit=8)
        if not mounts and not big:
            self.ui.warn("Couldn't read disk information on this system.")
            return 1
        self.ui.show_disk(mounts, big, scanned_path=home,
                          suggest_ncdu=not _sysinfo.has_ncdu())
        return 0

    def _cmd_process(self, arg: str) -> int:
        """Show what's running (or what holds a port) and offer to stop it."""
        port = _sysinfo.extract_port(arg) if arg else None
        if port is not None:
            procs = _sysinfo.processes_on_port(port)
            if not procs:
                self.ui.info(f"Nothing is listening on port {port}.")
                return 0
            self.ui.show_processes(procs, title=f"Using port {port}")
        else:
            procs = _sysinfo.top_processes(limit=10)
            if not procs:
                self.ui.warn("Couldn't read the list of running programs.")
                return 1
            self.ui.show_processes(procs, title="Heaviest programs (by memory)")

        if self.dry_run:
            return 0
        self.ui.blank()
        self.ui.info("Stop one of these? Enter its number, or 'q' to leave them be.")
        idx = self.ui.prompt_choice(len(procs))
        if idx is None:
            return 0
        command = f"kill {procs[idx].pid}"
        verdict = _safety.validate(command)
        if not verdict.allowed:
            self.ui.error(verdict.reason)
            return 2
        if not self.ui.confirm(command):
            self.ui.info("Okay — left it running.")
            return 0
        result = execute(command, on_line=lambda ln: self.ui.console.print(ln, markup=False))
        if result.succeeded:
            self.ui.success(f"Sent the stop signal to process {procs[idx].pid}.")
        return result.exit_code if result.executed else 0

    def _cmd_learn(self) -> int:
        """Launch the interactive, distro-aware terminal tutorial."""
        from .learner import Tutorial

        tutorial = Tutorial(system=self.system, presenter=self.ui, config=self.config)
        return tutorial.run()

    def _cmd_explain(self, rest: list[str]) -> int:
        """Toggle teaching mode, or explain a specific command the user typed.

        ``/explain on|off`` (or bare ``/explain``) toggles the teaching block on
        installs. ``/explain ls -la /etc`` instead breaks that exact command
        down, flag by flag — so a beginner can ask about *anything*.
        """
        if not rest or rest[0].lower() in ("on", "off"):
            return self._cmd_toggle("explain", rest[0].lower() if rest else "")
        command = " ".join(rest)
        parts = self.teacher.explain_arbitrary_command(command)
        if not parts:
            self.ui.warn(f"I don't recognise anything in \"{command}\" to explain yet.")
            return 1
        self.ui.show_explanation(parts)
        return 0

    def _meaningful_terms(self, query: str) -> list[str]:
        """Extract literal package-name candidates from a raw query.

        Strips filler/stopwords ("install", "i want to", …) but, unlike the
        intent normaliser, does *not* singularise — so real package names like
        "nodejs" survive intact. "install firefox" -> ["firefox"]. Used as a
        last-resort search when intent mapping yields nothing.
        """
        import re

        from .backends.basic_backend import _STOPWORDS

        cleaned = re.sub(r"[^a-z0-9+._-]", " ", query.lower())
        return [t for t in cleaned.split() if t and t not in _STOPWORDS]

    def _offline_candidates(self, candidates: list[str]):
        """Build SearchResults from the static map when live search is empty."""
        from .searcher import SearchResult

        backend = self.resolver._backend
        out = []
        for name in candidates:
            desc = backend.describe(name) if hasattr(backend, "describe") else ""
            out.append(SearchResult(name=name, description=desc,
                                    repo="(offline)", source=self.system.package_manager))
        return out

    def _maybe_sync_first(self) -> None:
        """On rolling-release distros, offer to refresh before installing.

        Installing a single package against a stale database is the classic
        Arch "partial upgrade" trap: the version in your local list may already
        be gone from the mirrors, giving a 404. We explain this in plain words
        and offer to sync first (default Yes). Never forced — the user can decline.
        """
        sync = self.system.sync_cmd
        if not sync or self.dry_run:
            return
        self.ui.blank()
        if self.system.package_manager == "pacman":
            self.ui.info(
                "On Arch-based systems, installing a single package without "
                "refreshing first can fail (the version in your local list may "
                "already be gone from the servers — the dreaded 404)."
            )
        else:
            self.ui.info("It's good practice to refresh your package list before installing.")
        if not self.ui.ask_yes_no(f"Refresh the system first with '{sync}'?", default_no=False):
            self.ui.info("Okay — skipping the refresh.")
            return
        self.ui.blank()
        self.ui.status_line(self.config.mode, "Refreshing package database...")
        result = execute(sync)
        if not result.succeeded:
            self.ui.warn("Refresh didn't complete cleanly — continuing anyway.")

    def _update_command(self, package: str, origin: str) -> str:
        """Build the right *update* command for an installed package's source.

        An AUR package must be updated through the AUR helper (plain pacman
        won't rebuild it); apt/dnf/zypper have dedicated upgrade verbs so we
        never accidentally pull in a fresh install of something else.
        """
        pm = self.system.package_manager
        if pm == "pacman":
            if origin == _installed.ORIGIN_AUR and self.system.aur_helper:
                return f"{self.system.aur_helper} -S {package}"
            return f"sudo pacman -S {package}"
        if pm == "apt":
            return f"sudo apt install --only-upgrade {package}"
        if pm == "dnf":
            return f"sudo dnf upgrade {package}"
        if pm == "zypper":
            return f"sudo zypper update {package}"
        return f"{self.system.install_cmd} {package}"

    def _install(self, package: str, *, source: str = "") -> int:
        """Confirm and run the install (or update) command for a single package."""
        # Already on the system? Offer an update through the same source it
        # was installed from, instead of a blind reinstall.
        info = _installed.get_info(package, self.system.package_manager)
        if info is not None:
            origin = ("the AUR" if info.origin == _installed.ORIGIN_AUR
                      else "the official repos")
            self.ui.blank()
            self.ui.info(
                f"[bold]{package}[/] is already installed "
                f"(version {info.version}, from {origin})."
            )
            if not self.ui.ask_yes_no("Update it through the same source?",
                                      default_no=False):
                self.ui.info("Okay — leaving it as it is.")
                return 0
            command = self._update_command(package, info.origin)
        elif source == "aur" and self.system.aur_helper:
            command = f"{self.system.aur_helper} -S {package}"
        else:
            command = f"{self.system.install_cmd} {package}"

        verdict = _safety.validate(command)
        if not verdict.allowed:
            self.ui.error(verdict.reason)
            return 2
        command = verdict.sanitized or command

        # On rolling-release distros, offer a refresh to avoid partial upgrades.
        self._maybe_sync_first()

        if self.config.explain:
            self._explain_command(command, package)

        self.ui.blank()
        self.ui.show_command(command)

        if self.dry_run:
            self.ui.info("[dim](dry-run: nothing was executed)[/]")
            execute(command, dry_run=True)
            return 0

        if not self.ui.confirm(command):
            _logger.log_event(_logger.EVENT_DECLINE, command)
            self.ui.info("Okay — nothing installed.")
            return 0

        self.ui.blank()
        self.ui.status_line(self.config.mode, f"Installing {package}...")
        result = execute(command, on_line=lambda ln: self.ui.console.print(ln, markup=False))
        if result.succeeded:
            self.ui.success(f"Done! Try running '{package}'.")
            return 0
        if result.exit_code >= 128:
            self.ui.info("Cancelled — nothing was changed.")
            return result.exit_code
        self.ui.error(f"Install exited with code {result.exit_code}.")
        return result.exit_code

    def _explain_command(self, command: str, package: str) -> None:
        """Render a teaching block for an install command via the Teacher."""
        parts = self.teacher.explain_command(command, package=package)
        self.ui.show_explanation(parts)

    # -- /mistake hook: analyse a failed command ----------------------------

    def analyze_error(self, command: str, exit_code: int, stderr: str = "") -> int:
        """Diagnose a failed command (called by the shell hook)."""
        # Exit codes >= 128 mean the command was killed by a signal — most
        # commonly the user's own Ctrl+C (130) or kill (143). A deliberate
        # cancellation is not a mistake; stay completely silent. (The hook
        # also filters these, but old hooks in existing rc files don't.)
        if exit_code >= 128:
            return 0
        ctx = _rules.ErrorContext(
            command=command,
            exit_code=exit_code,
            stderr=stderr,
            distro_id=self.system.distro_id,
            package_manager=self.system.package_manager,
            install_cmd=self.system.install_cmd,
        )
        # Prefer the configured backend chain (AI tiers can explain novel
        # errors); the chain always ends at Basic mode's rule engine.
        backend = getattr(self.resolver, "_backend", None)
        analyze = getattr(backend, "analyze_error", None)
        correction = analyze(ctx) if analyze else _rules.analyze(ctx)
        if correction is None:
            return 0  # Stay silent — nothing useful to say.
        self.ui.blank()
        self.ui.show_correction(correction)
        if correction.fix and not self.dry_run:
            if self.ui.confirm(correction.fix):
                result = execute(correction.fix, event=_logger.EVENT_FIX,
                                 on_line=lambda ln: self.ui.console.print(ln, markup=False))
                return result.exit_code
        return 0

    # -- Slash commands -----------------------------------------------------

    def slash(self, parts: list[str]) -> int:
        """Dispatch a /slash command."""
        name = parts[0].lstrip("/").lower()
        rest = parts[1:]                       # preserves case (paths, filenames)
        arg = rest[0].lower() if rest else ""  # for simple single-word commands
        joined = " ".join(rest)                # for free-text task commands
        handler = {
            "status": self._cmd_status,
            "help": self._cmd_help,
            "explain": lambda: self._cmd_explain(rest),
            "mistake": lambda: self._cmd_toggle("mistake", arg),
            "switch": lambda: self._cmd_switch(arg),
            "setup": self._cmd_setup,
            "cheat": lambda: self._cmd_cheat(arg),
            "man": lambda: self._cmd_man(joined),
            "do": lambda: self._cmd_do(joined),
            "disk": self._cmd_disk,
            "process": lambda: self._cmd_process(joined),
            "learn": self._cmd_learn,
        }.get(name)
        if handler is None:
            self.ui.warn(f"Unknown command '/{name}'. Try /help.")
            return 1
        return handler() or 0

    def _cmd_status(self) -> int:
        s, c = self.system, self.config
        self.ui.blank()
        self.ui.status_line(c.mode, "current settings")
        self.ui.info(f"  Mode:     {c.mode}")
        self.ui.info(f"  Explain:  {'on' if c.explain else 'off'}")
        self.ui.info(f"  Mistake:  {'on' if c.mistake else 'off'}")
        self.ui.info(f"  Distro:   {s.distro_name}")
        self.ui.info(f"  PM:       {s.package_manager}"
                     + (f" (+{s.aur_helper} for AUR)" if s.aur_helper else ""))
        self.ui.info(f"  Shell:    {s.shell}")
        return 0

    def _cmd_help(self) -> int:
        # Printed with markup disabled so the [option|option] brackets in the
        # command syntax aren't swallowed by rich's markup parser.
        lines = [
            "Novato — from novato to pro",
            "",
            "  INSTALL & DO THINGS",
            '  novato "what you want"                install software by describing it',
            '  novato "remove firefox"               uninstall a package you no longer want',
            '  novato "unzip this file"              do a terminal task in plain English',
            '  /do "rename a file"                   same, as an explicit command',
            '  /man "extract a tar file"             show the one command for a task',
            "",
            "  LEARN & LOOK UP",
            "  /learn                                interactive step-by-step tutorial",
            "  /cheat [topic]                        quick command reference (files, network...)",
            "  /explain ls -la                       explain any command, flag by flag",
            "  /explain [on|off]                     toggle teaching mode on installs",
            "",
            "  INSPECT YOUR SYSTEM",
            "  /disk                                 see what's filling up your disk",
            "  /process [port]                       see what's running / using a port",
            "",
            "  SETTINGS",
            "  /switch [online|offline|both|basic]   change AI mode",
            "  /mistake [on|off]                     toggle the silent error watcher",
            "  /status                               show current settings",
            "  /setup                                re-run the first-time setup wizard",
            "  /help                                 show this help",
        ]
        self.ui.blank()
        for line in lines:
            self.ui.console.print(line, markup=False)
        return 0

    def _cmd_toggle(self, key: str, arg: str) -> int:
        current = getattr(self.config, key)
        new = {"on": True, "off": False}.get(arg, not current)
        self.config = _config.update_config(**{key: new})
        self.ui.success(f"{key} mode is now {'on' if new else 'off'}.")
        if key == "mistake":
            self._sync_mistake_hook(new)
        return 0

    def _sync_mistake_hook(self, enabled: bool) -> None:
        """Install or remove the shell hook to match the /mistake setting."""
        shell = self.system.shell
        if not _watcher.supported_shell(shell):
            self.ui.warn(
                f"Your shell ('{shell}') isn't supported for auto-hooks yet. "
                "Novato still works — just run commands through it directly."
            )
            return
        if enabled:
            changed, msg = _watcher.install_hook(shell)
            (self.ui.info if changed else self.ui.warn)(msg)
            # If the hook is already live in *this* shell, nothing more to do.
            if os.environ.get("NOVATO_MISTAKE_ACTIVE") == "1":
                self.ui.success("It's already active in this terminal — you're set.")
                return
            # A child process can't reload the parent shell, so spoon-feed the
            # one remaining step in the simplest possible terms.
            self.ui.blank()
            self.ui.success("One last step to switch it on:")
            self.ui.info("  👉 Just close this terminal and open a new one.")
            self.ui.info(f"     (or, if you prefer, run:  source ~/.{shell}rc )")
            self.ui.blank()
            self.ui.info("After that, Novato silently watches for failed commands "
                         "and offers a fix whenever one breaks.")
        else:
            changed, msg = _watcher.uninstall_hook(shell)
            (self.ui.info if changed else self.ui.warn)(msg)

    def download_model(self, name: str = "auto") -> int:
        """Download an offline llamafile model and enable offline mode."""
        from . import downloader as _dl
        from .setup_wizard import download_model_with_progress

        if name in ("auto", "", None):
            spec = _dl.select_model()
        else:
            spec = _dl.MODELS.get(name.lower())
            if spec is None:
                self.ui.error(
                    f"Unknown model '{name}'. Available: "
                    + ", ".join(_dl.MODELS)
                )
                return 1

        if _dl.is_downloaded(spec):
            path = _dl.model_path(spec)
            self.ui.success(f"{spec.name} is already downloaded at {path}.")
        else:
            path = download_model_with_progress(spec, self.ui)
            if path is None:
                return 1

        # Point config at it and switch on the offline tier.
        new_mode = "both" if self.config.has_groq else "offline"
        self.config = _config.update_config(
            llamafile_path=str(path), llamafile_model=spec.name, mode=new_mode
        )
        self.ui.success(f"Offline mode enabled (mode: {new_mode}).")
        return 0

    def _cmd_setup(self) -> int:
        from .setup_wizard import SetupWizard

        wizard = SetupWizard(system=self.system, presenter=self.ui)
        self.config = wizard.run()
        return 0

    def _cmd_switch(self, arg: str) -> int:
        if not arg:
            self.ui.blank()
            self.ui.info(f"Current mode: [bold]{self.config.mode}[/]\n")
            for mode, desc in _switcher.mode_menu():
                marker = " ⭐" if mode == _switcher.RECOMMENDED_MODE else ""
                self.ui.info(f"  [bold cyan]{mode:<8}[/] {desc}{marker}")
            self.ui.info("\nUse: /switch <mode>")
            return 0
        try:
            self.config = _switcher.switch(arg)
        except _switcher.ModeSwitchError as exc:
            self.ui.error(str(exc))
            return 1
        self.ui.success(f"Switched to {arg} mode.")
        self._warn_if_mode_not_ready()
        return 0

    def _warn_if_mode_not_ready(self) -> None:
        """Flag a mode the user just selected that can't actually run yet.

        The router falls back to Basic automatically, so nothing breaks — but a
        beginner who picks 'online' with no key would otherwise have no idea why
        answers aren't smarter. Warn, and point at the exact fix.
        """
        mode = self.config.mode
        needs_groq = mode in ("online", "both") and not self.config.has_groq
        needs_model = mode in ("offline", "both") and not self.config.has_llamafile

        if needs_groq:
            self.ui.warn(
                "No Groq API key is set yet, so this mode falls back to Basic. "
                "Run /setup to add a free key (takes a minute)."
            )
        if needs_model:
            self.ui.warn(
                "No offline model is downloaded yet, so this mode falls back to "
                "Basic. Run  novato --download-model  to enable it."
            )


# ---------------------------------------------------------------------------
# Argument parsing / entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="novato",
        description="Install software by describing what you want. From novato to pro.",
        add_help=True,
    )
    p.add_argument("--version", action="version", version=f"novato {__version__}")
    p.add_argument("--dry-run", action="store_true",
                   help="show everything but never execute any command")
    p.add_argument("--analyze-error", nargs=2, metavar=("COMMAND", "EXIT_CODE"),
                   help="(internal) analyse a failed command; used by the shell hook")
    p.add_argument("--download-model", nargs="?", const="auto", metavar="MODEL",
                   help="download an offline llamafile model (auto-selects by RAM "
                        "if no name given) and enable offline mode")
    p.add_argument("words", nargs="*",
                   help='your request, e.g. "i want to edit videos", or a /command')
    return p


def _split_flags(raw: list[str]) -> tuple[list[str], list[str]]:
    """Separate leading global flags from the free-text/slash payload.

    A query or slash command may legitimately contain dashes — ``/explain ls
    -la``, ``find . -name x`` — which argparse would mistake for options. Global
    flags only ever appear at the *front*, so we peel those off (with their
    values) and pass everything from the first command/word onward verbatim.
    """
    head: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        tok = raw[i]
        if tok in ("--version", "-h", "--help", "--dry-run"):
            head.append(tok)
            i += 1
        elif tok == "--analyze-error":
            head.extend(raw[i:i + 3])  # flag + its two values
            i += 3
        elif tok == "--download-model":
            head.append(tok)
            i += 1
            if i < n and not raw[i].startswith(("/", "-")):
                head.append(raw[i])
                i += 1
        else:
            break  # first non-global token: payload begins here
    return head, raw[i:]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    raw = list(sys.argv[1:] if argv is None else argv)
    head, payload = _split_flags(raw)
    parser = _build_parser()
    args = parser.parse_args(head)
    args.words = payload
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        # Ctrl+C anywhere (menus, downloads, prompts): exit quietly, no
        # traceback. 130 = 128 + SIGINT, the shell convention.
        print("\nCancelled.")
        return 130


def _dispatch(args: argparse.Namespace) -> int:
    """Route parsed arguments to the right App entry point."""
    app = App(dry_run=args.dry_run)

    # First-run: setup_complete is False until the wizard finishes.
    if not app.config.setup_complete and not args.analyze_error and not args.download_model:
        app._cmd_setup()
        # Rebuild the app so the new config (mode, keys) is active.
        app = App(dry_run=args.dry_run)

    if args.download_model:
        return app.download_model(args.download_model)

    # Shell-hook path: analyse a failed command.
    if args.analyze_error:
        command, code_str = args.analyze_error
        try:
            code = int(code_str)
        except ValueError:
            code = 1
        stderr = sys.stdin.read() if not sys.stdin.isatty() else ""
        # The shell hook pipes the failed command's stderr in via stdin. To then
        # prompt the user for the fix, reconnect stdin to the controlling
        # terminal; if there's no TTY, confirm() degrades safely to "no".
        if not sys.stdin.isatty():
            try:
                sys.stdin = open("/dev/tty", "r")
            except OSError:
                pass
        return app.analyze_error(command, code, stderr)

    if not args.words:
        return app.slash(["/help"])

    # Slash command vs natural-language query.
    if args.words[0].startswith("/"):
        return app.slash(args.words)

    query = " ".join(args.words)
    return app.run_query(query)


if __name__ == "__main__":
    raise SystemExit(main())
