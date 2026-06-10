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
    ) -> None:
        self.system = system or detect_system()
        self.ui = presenter or Presenter(input_fn=input_fn)
        self._input = input_fn
        self._verify_groq = verify_groq or _default_verify_groq
        self._open_browser = open_browser
        # Injectable so tests never hit the network; defaults to the real
        # progress-bar download.
        self._download_fn = download_fn or download_model_with_progress

    # -- Public entry -------------------------------------------------------

    def run(self) -> _config.Config:
        """Run the wizard and return (and persist) the resulting config."""
        self._welcome()
        cfg = _config.load_config()

        choice = self._ask_mode()
        if choice == "s":
            cfg.mode = "basic"
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
        cfg.setup_complete = True
        _config.save_config(cfg)

        self._finish(cfg)
        return cfg

    # -- Steps --------------------------------------------------------------

    def _welcome(self) -> None:
        self.ui.blank()
        self.ui.info("[bold green]Welcome to Novato 🌱[/]")
        self.ui.info('[dim]"From novato to pro"[/]\n')
        self.ui.info("Detecting your system...")
        s = self.system
        if s.supported:
            self.ui.success(f"Distro:          {s.distro_name}")
            aur = f" (+{s.aur_helper} for AUR)" if s.aur_helper else (
                " (install yay/paru for AUR)" if s.supports_aur else "")
            self.ui.success(f"Package manager: {s.package_manager}{aur}")
            self.ui.success(f"Shell:           {s.shell}")
        else:
            self.ui.warn(f"Distro '{s.distro_name}' isn't supported yet — "
                         "Basic mode features are limited here.")
        self.ui.blank()
        self.ui.info("Basic mode is active right now — works immediately, no setup needed.\n")

    def _ask_mode(self) -> str:
        # Printed with markup disabled so the [1]/[s] option brackets aren't
        # swallowed by rich's markup parser ([s] = strikethrough). The offline
        # LLM is just one option here — [s] Skip keeps you on Basic mode.
        lines = [
            "Want Novato to handle complex requests? Choose your AI engine:",
            "",
            "  [1] Offline LLM (llamafile)  — private, works without internet (optional download)",
            "  [2] Online AI (Groq)         — fastest anywhere, completely free",
            "  [3] Both                     — Groq online + llamafile fallback   ⭐ RECOMMENDED",
            "  [s] Skip — stay on Basic mode for now (no AI, always works)",
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
        spec = _downloader.select_model()
        cfg.llamafile_model = spec.name
        self.ui.blank()
        self.ui.info(
            f"Offline LLM: your RAM suggests [bold]{spec.name}[/] (~{spec.approx_size})."
        )

        # Already have it? Just point at it.
        if _downloader.is_downloaded(spec):
            cfg.llamafile_path = str(_downloader.model_path(spec))
            self.ui.success(f"Model already downloaded at {cfg.llamafile_path}.")
            return

        # Opt-in: the default (empty answer) is NO so a multi-GB download is
        # never started just by pressing Enter. The offline tier is optional.
        answer = (self._safe_input(
            f"Download it now (~{spec.approx_size})? [y/N]: ") or "n").strip().lower()
        if answer not in ("y", "yes"):
            self.ui.warn("No problem — skipped the download. Enable it anytime with "
                         "'novato --download-model'.")
            return

        path = self._download_fn(spec, self.ui)
        if path is not None:
            cfg.llamafile_path = str(path)
            self.ui.success(f"Offline model ready at {path}.")
        else:
            self.ui.warn("Download didn't finish — you can retry with "
                         "'novato --download-model'.")

    def _setup_online(self, cfg: _config.Config) -> None:
        self.ui.blank()
        self.ui.info("Setting up Groq (free, no credit card)...")
        self.ui.info(f"Opening {GROQ_CONSOLE_URL} in your browser to create a key.")
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

    # -- helpers ------------------------------------------------------------

    def _safe_input(self, prompt: str) -> Optional[str]:
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None


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
