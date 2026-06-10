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
import sys
from typing import Optional, Sequence

from . import __version__
from . import config as _config
from . import logger as _logger
from . import rules as _rules
from . import safety as _safety
from . import switcher as _switcher
from . import watcher as _watcher
from .detector import SystemInfo, detect_system
from .executor import execute
from .intent import IntentResolver
from .presenter import Presenter
from .ranker import rank
from .searcher import search_candidates
from .teacher import Teacher


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
        """Resolve an intent, search repos, present options, install one."""
        if not self.system.supported:
            self.ui.error(
                f"Your distro ({self.system.distro_name}) isn't supported yet. "
                "Novato needs a known package manager."
            )
            return 2

        mode = self.config.mode
        self.ui.status_line(mode, "Searching repositories...")

        plan = self.resolver.resolve(query)
        if not plan.understood:
            self.ui.warn(
                f"I couldn't map \"{query}\" to packages yet. Try simpler words "
                "(e.g. \"video editor\"), or enable an AI mode with /switch."
            )
            return 1

        _logger.log_event(_logger.EVENT_SEARCH, query, note=plan.matched_intent)

        results = search_candidates(
            plan.candidates,
            self.system.package_manager,
            include_aur=self.system.supports_aur,
        )
        # Fall back to offline descriptions if live search returned nothing
        # (e.g. no network / inside a sandbox): present the curated candidates.
        if not results:
            results = self._offline_candidates(plan.candidates)
        if not results:
            self.ui.warn("No matching packages found in your repositories.")
            return 1

        ranked = rank(
            results, query=query, preferred_order=plan.candidates, limit=8
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

    def _install(self, package: str, *, source: str = "") -> int:
        """Confirm and run the install command for a single package."""
        if source == "aur" and self.system.aur_helper:
            command = f"{self.system.aur_helper} -S {package}"
        else:
            command = f"{self.system.install_cmd} {package}"

        verdict = _safety.validate(command)
        if not verdict.allowed:
            self.ui.error(verdict.reason)
            return 2
        command = verdict.sanitized or command

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
        self.ui.error(f"Install exited with code {result.exit_code}.")
        return result.exit_code

    def _explain_command(self, command: str, package: str) -> None:
        """Render a teaching block for an install command via the Teacher."""
        parts = self.teacher.explain_command(command, package=package)
        self.ui.show_explanation(parts)

    # -- /mistake hook: analyse a failed command ----------------------------

    def analyze_error(self, command: str, exit_code: int, stderr: str = "") -> int:
        """Diagnose a failed command (called by the shell hook)."""
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
        """Dispatch a /slash command. Full implementations land in Phase 4."""
        name = parts[0].lstrip("/").lower()
        arg = parts[1].lower() if len(parts) > 1 else ""
        handler = {
            "status": self._cmd_status,
            "help": self._cmd_help,
            "explain": lambda: self._cmd_toggle("explain", arg),
            "mistake": lambda: self._cmd_toggle("mistake", arg),
            "switch": lambda: self._cmd_switch(arg),
            "setup": self._cmd_setup,
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
            '  novato "what you want"                install software by describing it',
            "  /switch [online|offline|both|basic]   change AI mode",
            "  /explain [on|off]                     toggle teaching mode",
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
        return 0


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

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
