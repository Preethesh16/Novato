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
            self.ui.success("Staying on Basic mode — you're all set.")
            return cfg

        if choice in ("1", "3"):  # offline or both
            self._setup_offline(cfg)
        if choice in ("2", "3"):  # online or both
            self._setup_online(cfg)

        cfg.mode = {"1": "offline", "2": "online", "3": "both"}.get(choice, "basic")
        # If a tier the user picked didn't actually get configured, degrade.
        if cfg.mode in ("online", "both") and not cfg.has_groq and not cfg.has_llamafile:
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
        self.ui.info("Want Novato to handle complex requests? Choose your AI engine:\n")
        self.ui.info("  [1] Offline LLM (llamafile)  — private, works without internet")
        self.ui.info("  [2] Online AI (Groq)         — fastest anywhere, completely free")
        self.ui.info("  [3] Both                     — Groq online + llamafile fallback "
                     "[bold yellow]⭐ RECOMMENDED[/]")
        self.ui.info("  [s] Skip — stay on Basic mode for now\n")
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

        answer = (self._safe_input(
            f"Download it now (~{spec.approx_size})? [Y/n]: ") or "y").strip().lower()
        if answer in ("n", "no"):
            self.ui.warn("Skipped the download — enable it later with "
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
        self.ui.success("Novato is set up! 🎉")
        self.ui.status_line(cfg.mode, "active mode")
        self.ui.info("\nTry it:")
        self.ui.info('  novato "i want to edit photos"')
        self.ui.info("  /explain on")
        self.ui.info("  /mistake on")
        self.ui.info("  /help")

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
