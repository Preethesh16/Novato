# SPDX-License-Identifier: GPL-3.0-or-later
"""First-run onboarding wizard.

Walks a brand-new user through detecting their system and (optionally) enabling a
smarter AI tier. The guiding principle is *zero friction*: Basic mode already
works, so every step here is skippable and the user can always pick ``[s]`` to
stay on Basic.

The wizard is deliberately decoupled from I/O specifics — it takes a
:class:`novato.presenter.Presenter` and an input function — so it can be driven
by tests without a TTY and re-run any time via ``/setup``.
"""

from __future__ import annotations

import webbrowser
from typing import Callable, Optional

from . import config as _config
from . import downloader as _downloader
from . import watcher as _watcher
from .backends.groq_backend import GroqBackend
from .detector import SystemInfo, detect_system
from .presenter import Presenter

GROQ_CONSOLE_URL = "https://console.groq.com/keys"


class SetupWizard:
    """Interactive first-run setup."""

    def __init__(
        self,
        *,
        system: Optional[SystemInfo] = None,
        presenter: Optional[Presenter] = None,
        input_fn: Callable[[str], str] = input,
        verify_groq: Optional[Callable[[str], bool]] = None,
        open_browser: Callable[[str], bool] = webbrowser.open,
        download_fn: Optional[Callable] = None,
        install_hook_fn: Optional[Callable] = None,
    ) -> None:
        self.system = system or detect_system()
        self.ui = presenter or Presenter(input_fn=input_fn)
        self._input = input_fn
        self._verify_groq = verify_groq or _default_verify_groq
        self._open_browser = open_browser
        # Injectable so tests never hit the network; defaults to the real
        # progress-bar download.
        self._download_fn = download_fn or download_model_with_progress
        # Injectable so tests never touch the real ~/.zshrc.
        self._install_hook = install_hook_fn or _watcher.install_hook

    # -- Public entry -------------------------------------------------------

    def run(self) -> _config.Config:
        """Run the wizard and return (and persist) the resulting config."""
        self._welcome()
        cfg = _config.load_config()

        choice = self._ask_mode()
        if choice == "s":
            cfg.mode = "basic"
            self._setup_mistake_watcher(cfg)
            cfg.setup_complete = True
            _config.save_config(cfg)
            self._finish(cfg)
            return cfg

        if choice in ("1", "3"):  # offline or both
            self._setup_offline(cfg)
        if choice in ("2", "3"):  # online or both
            self._setup_online(cfg)

        cfg.mode = {"1": "offline", "2": "online", "3": "both"}.get(choice, "basic")
        # Degrade gracefully so the saved mode reflects what's actually usable:
        #   - offline but no model downloaded  -> basic
        #   - online/both but no Groq key      -> the other configured tier, or basic
        if cfg.mode == "offline" and not cfg.has_llamafile:
            cfg.mode = "basic"
        elif cfg.mode == "online" and not cfg.has_groq:
            cfg.mode = "basic"
        elif cfg.mode == "both":
            if cfg.has_groq and not cfg.has_llamafile:
                cfg.mode = "online"
            elif cfg.has_llamafile and not cfg.has_groq:
                cfg.mode = "offline"
            elif not cfg.has_groq and not cfg.has_llamafile:
                cfg.mode = "basic"
        self._setup_mistake_watcher(cfg)

        cfg.setup_complete = True
        _config.save_config(cfg)

        self._finish(cfg)
        return cfg

    # -- Steps --------------------------------------------------------------

    def _welcome(self) -> None:
        from rich.panel import Panel
        from rich.text import Text

        self.ui.blank()
        banner = Text()
        banner.append("Welcome to Novato!  🌱\n\n", style="bold green")
        banner.append("New to Linux? Tired of remembering commands?\n", style="bold")
        banner.append("No worries — Novato is here.\n\n")
        banner.append("Just say what you want, in your own words:\n", style="dim")
        banner.append('    novato "i want to edit videos"\n', style="bold cyan")
        banner.append('    novato "something to listen to music"', style="bold cyan")
        self.ui.console.print(Panel(
            banner,
            title="🌱 novato",
            subtitle="from novato to pro",
            border_style="green",
            expand=False,
            padding=(1, 3),
        ))
        self.ui.blank()
        self.ui.info("Let's get you set up — it takes under a minute.")
        self.ui.blank()
        self.ui.info("Checking your computer...")
        s = self.system
        if s.supported:
            aur = f" (+{s.aur_helper} for AUR)" if s.aur_helper else (
                " (install yay/paru for AUR)" if s.supports_aur else "")
            self.ui.success(f"You're running:  {s.distro_name}")
            self.ui.success(f"App store:       {s.package_manager}{aur}")
            self.ui.success(f"Terminal shell:  {s.shell}")
        else:
            self.ui.warn(f"Distro '{s.distro_name}' isn't supported yet — "
                         "Basic mode features are limited here.")
        self.ui.blank()
        self.ui.info("[dim]Good news: Novato already works right now (Basic mode, no "
                     "internet or signup needed). The next step just makes it smarter.[/]\n")

    def _ask_mode(self) -> str:
        # Printed with markup disabled so the [1]/[s] option brackets aren't
        # swallowed by rich's markup parser ([s] = strikethrough). The offline
        # LLM is just one option here — [s] Skip keeps you on Basic mode.
        lines = [
            "Want Novato to handle complex requests? Choose your AI engine:",
            "",
            "  [1] Offline LLM (llamafile)  — private, works without internet (one-time download)",
            "  [2] Online AI (Groq)         — fastest & smartest, completely free (needs internet)",
            "  [3] Both                     — Groq when online, local LLM when offline",
            "  [s] Skip — stay on Basic mode for now (no AI, always works)",
            "",
            "  Not sure? Here's the simple rule:",
            "    • Have internet?  pick [2] Groq — best results, no download  ⭐",
            "    • Often offline, or want 100% privacy?  pick [1]",
            "    • Want both worlds (download needed too)?  pick [3]",
            "",
        ]
        for line in lines:
            self.ui.console.print(line, markup=False)
        while True:
            choice = (self._safe_input("Pick [1/2/3/s]: ") or "s").strip().lower()
            if choice in ("1", "2", "3", "s"):
                return choice
            self.ui.warn("Please choose 1, 2, 3, or s.")

    def _setup_offline(self, cfg: _config.Config) -> None:
        recommended = _downloader.select_model()
        all_models = list(_downloader.MODELS.values())

        _MODEL_NOTES = {
            "tinyllama-1.1b": "simple requests, lowest RAM",
            "phi3-mini":      "good reasoning, best size/quality balance",
            "mistral-7b":     "strong general knowledge, nuanced queries",
            "llama3.1-8b":    "best quality, handles anything",
        }

        self.ui.blank()
        self.ui.console.print("Choose an offline model to download:\n", markup=False)
        for i, spec in enumerate(all_models, start=1):
            tag = "  <-- recommended for your RAM" if spec.name == recommended.name else ""
            line = (
                f"  [{i}] {spec.name:<18}"
                f"  {spec.approx_size:<8}"
                f"  needs {spec.min_ram_gb:.0f} GB RAM"
                f"  — {_MODEL_NOTES.get(spec.name, '')}"
                f"{tag}"
            )
            self.ui.console.print(line, markup=False)
        self.ui.console.print(
            "\n  [s] Skip — download later with 'novato --download-model'\n",
            markup=False,
        )

        valid = {str(i): spec for i, spec in enumerate(all_models, start=1)}
        valid["s"] = None  # type: ignore[assignment]
        while True:
            choice = (self._safe_input(f"Pick [1-{len(all_models)}/s]: ") or "s").strip().lower()
            if choice in valid:
                break
            self.ui.warn(f"Please choose a number between 1 and {len(all_models)}, or s.")

        if choice == "s":
            self.ui.warn("Skipped — you can download a model anytime with "
                         "'novato --download-model'.")
            return

        spec = valid[choice]
        cfg.llamafile_model = spec.name

        # Already downloaded? Just point at it.
        if _downloader.is_downloaded(spec):
            cfg.llamafile_path = str(_downloader.model_path(spec))
            self.ui.success(f"Model already downloaded at {cfg.llamafile_path}.")
            return

        # Confirm before starting a potentially large download (default = No).
        answer = (self._safe_input(
            f"Download {spec.name} (~{spec.approx_size}) now? [y/N]: ") or "n").strip().lower()
        if answer not in ("y", "yes"):
            self.ui.warn("No problem — skipped. Run 'novato --download-model' anytime.")
            return

        path = self._download_fn(spec, self.ui)
        if path is not None:
            cfg.llamafile_path = str(path)
            self.ui.success(f"Offline model ready at {path}.")
        else:
            self.ui.warn("Download didn't finish — retry with 'novato --download-model'.")

    def _setup_online(self, cfg: _config.Config) -> None:
        self.ui.blank()
        self.ui.info("Setting up Groq (free, no credit card)...")
        self.ui.blank()
        # Spoon-fed, numbered steps — assume the user has never seen an API
        # key before. Printed with markup off so nothing gets eaten by rich.
        steps = [
            "How to get your free Groq API key (takes ~1 minute):",
            "",
            "  Step 1: Your browser is opening https://console.groq.com/keys",
            "          (if it didn't open, type that address yourself)",
            "  Step 2: Sign up with your email (or Google/GitHub) — it's free,",
            "          no credit card is ever asked.",
            "  Step 3: Once logged in, click the button 'Create API Key'.",
            "  Step 4: Give it any name (e.g. 'novato') and click Submit.",
            "  Step 5: A key starting with 'gsk_...' appears ONCE — click Copy.",
            "  Step 6: Come back to this terminal and paste it below",
            "          (right-click or Ctrl+Shift+V to paste in a terminal).",
            "",
        ]
        for line in steps:
            self.ui.console.print(line, markup=False)
        try:
            self._open_browser(GROQ_CONSOLE_URL)
        except Exception:
            pass
        key = (self._safe_input("Paste your Groq API key (or leave blank to skip): ") or "").strip()
        if not key:
            self.ui.warn("Skipped Groq setup — you can add a key later with /setup.")
            return
        self.ui.info("Verifying key...")
        if self._verify_groq(key):
            cfg.groq_api_key = key
            self.ui.success("Key verified — Groq connected.")
        else:
            self.ui.warn("Couldn't verify that key. Saving it anyway; check it with /status.")
            cfg.groq_api_key = key

    def _setup_mistake_watcher(self, cfg: _config.Config) -> None:
        """Offer to enable the silent error watcher during onboarding.

        This is the *right* time to set it up: the hook is written to the rc
        file now, so every new terminal the user opens already has it — they
        never have to run ``/mistake on`` or reload their shell themselves.
        """
        if not _watcher.supported_shell(self.system.shell):
            return
        self.ui.blank()
        self.ui.console.print(
            "Novato can quietly watch for failed commands and offer a fix when "
            "one breaks — completely silent while things work.",
            markup=False,
        )
        if not self.ui.ask_yes_no("Enable this mistake-watcher? (recommended)",
                                  default_no=False):
            cfg.mistake = False
            return
        changed, _msg = self._install_hook(self.system.shell)
        cfg.mistake = True
        self.ui.success("Mistake-watcher enabled — it activates automatically in "
                        "every new terminal you open.")

    def _finish(self, cfg: _config.Config) -> None:
        self.ui.blank()
        self.ui.success("Novato is ready! Here is what you can do:\n")
        lines = [
            "  INSTALL SOFTWARE BY DESCRIBING IT",
            '    novato "i want to edit videos"',
            '    novato "i need something to browse the web"',
            '    novato "i want to listen to music"',
            "",
            "  TEACHING MODE  —  learn what every command does as Novato runs it",
            "    /explain on      turn on step-by-step explanations",
            "    /explain off     turn off",
            "",
            "  SILENT ERROR WATCHER  —  Novato watches your shell and quietly fixes mistakes",
            "    /mistake on      enable (adds a hook to your shell)",
            "    /mistake off     disable",
            "",
            "  SWITCH AI MODE  —  change how smart Novato is",
            "    /switch          show available modes (basic / offline / online / both)",
            "    /switch online   use Groq (fast, free, needs internet)",
            "    /switch offline  use local LLM (private, no internet needed)",
            "    /switch both     Groq first, local LLM as fallback  ⭐",
            "",
            "  DOWNLOAD OFFLINE MODEL  —  one-time download for offline AI",
            "    novato --download-model",
            "",
            "  OTHER COMMANDS",
            "    /status          show current mode, distro, shell",
            "    /setup           re-run this setup wizard",
            "    /help            quick reference",
            "",
            f"  Active mode right now: {cfg.mode}",
            "",
        ]
        for line in lines:
            self.ui.console.print(line, markup=False)
        self.ui.info("[dim]Tip: run /explain on before your first install to see what each command means.[/]")
        # One last screen: the terminal survival shortcuts nobody tells you.
        self._show_terminal_tips(cfg)

    def _show_terminal_tips(self, cfg: _config.Config) -> None:
        """Show the one-time 'things nobody tells you' shortcuts panel.

        Shown only once ever (tracked by ``cfg.tips_shown``) so re-running
        ``/setup`` doesn't nag a returning user. These shortcuts — especially
        copy/paste — are the single biggest source of beginner frustration.
        """
        if cfg.tips_shown:
            return
        render_terminal_tips(self.ui)
        cfg.tips_shown = True
        try:
            _config.update_config(tips_shown=True)
        except OSError:
            pass

    # -- helpers ------------------------------------------------------------

    def _safe_input(self, prompt: str) -> Optional[str]:
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None


def render_terminal_tips(presenter: Presenter) -> None:
    """Render the 'things nobody tells new terminal users' shortcuts panel.

    Pure presentation, kept module-level so it can be reused (e.g. by tests or a
    future ``/tips`` command). The copy/paste warning is first on purpose: new
    users reflexively press Ctrl+C to copy and accidentally kill their command.
    """
    from rich.panel import Panel
    from rich.text import Text

    tips: list[tuple[str, str]] = [
        ("Copy text", "Ctrl+Shift+C"),
        ("Paste text", "Ctrl+Shift+V"),
        ("Auto-complete", "press Tab to finish a file or command name"),
        ("Last command", "press the ↑ (up) arrow"),
        ("Search history", "Ctrl+R, then type any part of an old command"),
        ("Stop a command", "Ctrl+C"),
        ("Clear the screen", "Ctrl+L"),
    ]
    body = Text()
    width = max(len(label) for label, _ in tips)
    for label, how in tips:
        body.append(f"  {label:<{width}}  →  ", style="bold cyan")
        body.append(how + "\n")
    body.append("\n  ⚠ ", style="bold yellow")
    body.append("To copy, use Ctrl+Shift+C — plain Ctrl+C STOPS the command!\n",
                style="yellow")
    body.append("\n  These save you hours. You're welcome. 🙂", style="dim")
    presenter.blank()
    presenter.console.print(Panel(
        body,
        title="⌨  Things nobody tells new terminal users",
        border_style="yellow",
        expand=False,
        padding=(1, 2),
    ))


def download_model_with_progress(spec, presenter: Presenter):
    """Download ``spec`` showing a live rich progress bar.

    Returns the finished :class:`pathlib.Path`, or ``None`` on failure. Used by
    the setup wizard and the ``novato --download-model`` command.
    """
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )

    presenter.info(f"Downloading {spec.name} ({spec.approx_size})...")
    presenter.info(f"[dim]{spec.url.split('?')[0]}[/]")
    try:
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=presenter.console,
        ) as progress:
            task = progress.add_task("llamafile", total=None)

            def on_progress(downloaded: int, total: Optional[int]) -> None:
                progress.update(task, completed=downloaded, total=total)

            path = _downloader.download_model(spec, progress=on_progress)
        return path
    except _downloader.DownloadError as exc:
        presenter.error(str(exc))
        return None
    except KeyboardInterrupt:
        presenter.warn("Download interrupted — it will resume next time.")
        return None


def _default_verify_groq(key: str) -> bool:
    """Verify a Groq key with a tiny live request. Returns False on any failure."""
    backend = GroqBackend(key)
    if not backend.available:
        return False
    # A trivial intent that should always return at least one candidate.
    result = backend.resolve_intent("web browser")
    return result.found
