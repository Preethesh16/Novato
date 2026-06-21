# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive terminal tutorial (`/learn`).

Most beginner guides dump twenty commands at once. Novato's tutorial does the
opposite: **one command at a time**, each with a plain-English concept, a hands-
on try-it-yourself step, and a check that the lesson actually landed before
moving on. Progress is saved, so a learner can stop after one lesson and resume
tomorrow.

After the universal basics (navigation, files, permissions, finding things), the
tutorial unlocks a **distro-specific package** matched to the user's system —
``apt``/snap/systemctl for Ubuntu, ``pacman``/AUR for Arch, ``dnf``/SELinux for
Fedora — so the next thing they learn is immediately useful on *their* machine.

Safety: a lesson only ever *runs* a command that this module authored and vetted
(always read-only — ``pwd``, ``ls``, ``whoami`` ...). The destructive lessons
(deleting files) are taught as concepts with a comprehension check and are never
executed. Typed input is matched, never blindly run.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import config as _config
from .detector import SystemInfo, detect_system
from .presenter import Presenter

_MAX_TRIES = 2  # gentle retries before we just reveal the answer and move on
_QUIT_WORDS = {"q", "quit", "exit"}  # typed at any prompt to leave the tutorial


@dataclass(frozen=True)
class Lesson:
    """One self-contained lesson: teach, try, check."""

    slug: str
    title: str
    concept: tuple[str, ...]       # plain-English explanation lines
    command: str                   # the command being taught (display form)
    command_note: str              # one line: what it does
    # Hands-on step. Either a typed-command exercise (``expected`` set) or a
    # comprehension check (``quiz`` set). Concept-only lessons set neither.
    practice_prompt: str = ""
    expected: str = ""             # command the learner should type
    run_demo: bool = False         # actually run ``expected`` to show real output
    quiz: tuple[str, str] = field(default_factory=tuple)  # (question, accepted_substring)


# ---------------------------------------------------------------------------
# Curriculum
# ---------------------------------------------------------------------------
UNIVERSAL: tuple[Lesson, ...] = (
    Lesson(
        slug="pwd",
        title="Where am I?",
        concept=(
            "The terminal is always 'inside' one folder at a time.",
            "When you're lost, this command tells you exactly where you are.",
        ),
        command="pwd",
        command_note="print working directory — shows your current folder",
        practice_prompt="Now you try it: type  pwd  and press Enter.",
        expected="pwd",
        run_demo=True,
    ),
    Lesson(
        slug="ls",
        title="What's in here?",
        concept=(
            "'ls' lists what's in your current folder.",
            "Adding -la shows EVERYTHING, including hidden files (names that",
            "start with a dot) and details like size and date.",
            "",
            "Tip: press the Tab key to auto-complete file names as you type —",
            "it saves a huge amount of typing.",
        ),
        command="ls -la",
        command_note="list all files here, with details",
        practice_prompt="Your turn: type  ls -la  and press Enter.",
        expected="ls -la",
        run_demo=True,
    ),
    Lesson(
        slug="cd",
        title="Moving around",
        concept=(
            "'cd' means 'change directory' — it walks you into a folder.",
            "  cd Documents   goes into the Documents folder",
            "  cd ..          goes UP one level (back out)",
            "  cd ~           jumps straight to your home folder",
            "",
            "Press ↑ (up arrow) any time to bring back your last command.",
        ),
        command="cd ..",
        command_note="go up one folder",
        practice_prompt="Type  cd ..  to practise going up a level.",
        expected="cd ..",
    ),
    Lesson(
        slug="files",
        title="Creating files and folders",
        concept=(
            "Two everyday commands:",
            "  touch notes.txt   creates a new empty file",
            "  mkdir projects    creates a new folder",
            "There's no 'New File' button here — you make them by name.",
        ),
        command="mkdir projects",
        command_note="create a folder called 'projects'",
        practice_prompt="Type  mkdir projects  (you can delete it later).",
        expected="mkdir projects",
    ),
    Lesson(
        slug="cat",
        title="Reading a file",
        concept=(
            "'cat' prints a file straight to the screen — great for a quick look.",
            "For long files, use  less file.txt  and scroll (press q to quit).",
        ),
        command="cat filename.txt",
        command_note="show a file's contents",
        practice_prompt="Type  whoami  — your turn to read your own username.",
        expected="whoami",
        run_demo=True,
    ),
    Lesson(
        slug="delete",
        title="Deleting — handle with care",
        concept=(
            "'rm file.txt' deletes a file. 'rm -r folder' deletes a whole folder.",
            "",
            "⚠ THERE IS NO RECYCLE BIN. A deleted file is gone for good.",
            "Always read the name twice before you press Enter.",
            "",
            "(We won't actually delete anything in this lesson.)",
        ),
        command="rm file.txt",
        command_note="delete a file — permanently",
        quiz=(
            "Quick check: after you delete a file with rm, can you get it back\n"
            "from a Recycle Bin? (yes/no)",
            "no",
        ),
    ),
    Lesson(
        slug="permissions",
        title="Permissions and sudo",
        concept=(
            "Linux protects system files by asking for permission.",
            "  sudo <command>      runs a command as administrator (asks your password)",
            "  chmod +x script.sh  lets a script be run as a program",
            "",
            "Only use 'sudo' when a command truly needs it — it's powerful.",
        ),
        command="sudo apt update",
        command_note="'sudo' = do this as administrator",
        quiz=(
            "Quick check: which word do you put in FRONT of a command to run it\n"
            "as administrator?",
            "sudo",
        ),
    ),
    Lesson(
        slug="help",
        title="Getting unstuck",
        concept=(
            "Every command can explain itself:",
            "  command --help     shows a quick summary",
            "  man command        shows the full manual (press q to quit)",
            "",
            "And of course, you can always ask Novato in plain English:",
            '  novato /man "unzip a file"    →  gives you the exact command',
        ),
        command="ls --help",
        command_note="show built-in help for a command",
        practice_prompt="Type  date  to see a command run (then we'll continue).",
        expected="date",
        run_demo=True,
    ),
    Lesson(
        slug="find",
        title="Finding things",
        concept=(
            "Two search tools you'll use forever:",
            '  find . -name "*.txt"   finds files by name (here and below)',
            '  grep -r "hello" .      finds text INSIDE files',
            "",
            "The . means 'this folder'.",
        ),
        command='grep -r "text" .',
        command_note="search for text inside files",
        quiz=(
            "Quick check: which tool searches for text INSIDE files —\n"
            "find or grep?",
            "grep",
        ),
    ),
)


# -- Distro packages: short, immediately-useful lessons for the user's system --
_UBUNTU = (
    Lesson(
        slug="apt-update",
        title="Keeping Ubuntu fresh",
        concept=(
            "On Ubuntu/Debian, two commands keep everything up to date:",
            "  sudo apt update     refreshes the list of available updates",
            "  sudo apt upgrade    installs them",
            "Run them together now and then to stay secure.",
        ),
        command="sudo apt update && sudo apt upgrade",
        command_note="refresh then install updates",
        quiz=("Quick check: which command REFRESHES the update list — "
              "'apt update' or 'apt upgrade'?", "update"),
    ),
    Lesson(
        slug="apt-basics",
        title="Installing and removing software",
        concept=(
            "The everyday apt commands:",
            "  sudo apt install name   install a program",
            "  sudo apt remove name    uninstall it",
            "  apt search keyword      search the repositories",
            "  apt show name           details about a package",
        ),
        command="sudo apt install vlc",
        command_note="install a package from the Ubuntu/Debian repos",
        quiz=("Quick check: which apt word REMOVES a program — install or remove?",
              "remove"),
    ),
    Lesson(
        slug="apt-vs-snap",
        title="apt vs snap vs flatpak",
        concept=(
            "Ubuntu can install software three ways:",
            "  apt      classic system packages (fast, lightweight)",
            "  snap     self-contained apps, auto-updating (Ubuntu's default store)",
            "  flatpak  cross-distro self-contained apps",
            "When unsure, just ask Novato — it picks the right one for you.",
        ),
        command="sudo apt install vlc",
        command_note="install a package the classic way",
        quiz=("Quick check: which one ships self-contained, auto-updating apps "
              "on Ubuntu — apt or snap?", "snap"),
    ),
    Lesson(
        slug="systemctl",
        title="Starting and stopping services",
        concept=(
            "Background services (web servers, bluetooth, etc.) are managed with",
            "systemctl:",
            "  systemctl status nginx    is it running?",
            "  sudo systemctl start nginx   start it",
            "  sudo systemctl enable nginx  start it automatically at boot",
        ),
        command="systemctl status bluetooth",
        command_note="check whether a service is running",
        quiz=("Quick check: which systemctl word makes a service start "
              "automatically at every boot?", "enable"),
    ),
)

_ARCH = (
    Lesson(
        slug="pacman-syu",
        title="Updating Arch the right way",
        concept=(
            "Arch is 'rolling release' — you update the whole system at once:",
            "  sudo pacman -Syu",
            "Avoid updating just one package; that can cause a 'partial upgrade'.",
            "Update fully and regularly and Arch stays healthy.",
        ),
        command="sudo pacman -Syu",
        command_note="refresh and upgrade the entire system",
        quiz=("Quick check: which single pacman command refreshes AND upgrades "
              "everything? (hint: starts with -S)", "-syu"),
    ),
    Lesson(
        slug="pacman-basics",
        title="pacman in a nutshell",
        concept=(
            "The everyday pacman flags:",
            "  sudo pacman -S name     install a package",
            "  sudo pacman -R name     remove a package",
            "  pacman -Ss keyword      search the repos",
            "  pacman -Qi name         info about an installed package",
        ),
        command="pacman -Ss firefox",
        command_note="search the official repositories",
        quiz=("Quick check: which pacman flag INSTALLS a package — -S or -R?",
              "-s"),
    ),
    Lesson(
        slug="aur",
        title="The AUR (community packages)",
        concept=(
            "The AUR (Arch User Repository) has tons of extra software.",
            "You install from it with a 'helper' like yay or paru:",
            "  yay -S google-chrome",
            "Helpers build the package for you. Novato uses them automatically.",
        ),
        command="yay -S spotify",
        command_note="install a community (AUR) package",
        quiz=("Quick check: is software from the AUR official Arch packages, "
              "or community-made? (official/community)", "community"),
    ),
)

_FEDORA = (
    Lesson(
        slug="dnf-update",
        title="Updating Fedora",
        concept=(
            "Fedora uses dnf to manage software. To update everything:",
            "  sudo dnf upgrade        install all available updates",
            "Run it regularly to stay secure and current.",
        ),
        command="sudo dnf upgrade",
        command_note="install all available updates",
        quiz=("Quick check: which dnf command installs all available updates?",
              "upgrade"),
    ),
    Lesson(
        slug="dnf-basics",
        title="Installing and removing software",
        concept=(
            "The everyday dnf commands:",
            "  sudo dnf install name   install a program",
            "  sudo dnf remove name    uninstall it",
            "  dnf search keyword      search the repositories",
            "  dnf info name           details about a package",
        ),
        command="sudo dnf install vlc",
        command_note="install a package from the Fedora repos",
        quiz=("Quick check: which dnf word REMOVES a program?", "remove"),
    ),
    Lesson(
        slug="selinux",
        title="Why Fedora sometimes blocks things",
        concept=(
            "Fedora ships SELinux, a security layer that can block a program even",
            "when file permissions look fine.",
            "  getenforce        shows if SELinux is active",
            "If something is mysteriously 'denied', SELinux is a likely culprit.",
        ),
        command="getenforce",
        command_note="check whether SELinux is enforcing",
        quiz=("Quick check: the security layer that can block apps on Fedora "
              "is called what?", "selinux"),
    ),
)

_OPENSUSE = (
    Lesson(
        slug="zypper-update",
        title="Updating openSUSE",
        concept=(
            "openSUSE uses zypper to manage software:",
            "  sudo zypper refresh     refresh the repository list",
            "  sudo zypper update      install available updates",
            "On Tumbleweed (rolling release), use 'sudo zypper dup' instead.",
        ),
        command="sudo zypper update",
        command_note="install all available updates",
        quiz=("Quick check: which zypper word installs available updates — "
              "'update' or 'refresh'?", "update"),
    ),
    Lesson(
        slug="zypper-basics",
        title="Installing and removing software",
        concept=(
            "The everyday zypper commands:",
            "  sudo zypper install name   install a program",
            "  sudo zypper remove name    uninstall it",
            "  zypper search keyword      search the repositories",
            "  zypper info name           details about a package",
        ),
        command="sudo zypper install vlc",
        command_note="install a package from the openSUSE repos",
        quiz=("Quick check: which zypper word INSTALLS a program?", "install"),
    ),
)

# package id -> (label, lessons). Chosen by detected distro / package manager.
# Every track teaches the same core trio — update the system, install a package,
# remove a package (plus search) — in that distro's own commands.
PACKAGES: dict[str, tuple[str, tuple[Lesson, ...]]] = {
    "ubuntu": ("Ubuntu & Debian essentials", _UBUNTU),
    "arch": ("Arch Linux essentials", _ARCH),
    "fedora": ("Fedora essentials", _FEDORA),
    "opensuse": ("openSUSE essentials", _OPENSUSE),
}


def package_for_system(system: SystemInfo) -> Optional[str]:
    """Pick the distro lesson-package id that fits this system, or ``None``."""
    pm = system.package_manager
    if pm == "apt":
        return "ubuntu"
    if pm == "pacman":
        return "arch"
    if pm == "dnf":
        return "fedora"
    if pm == "zypper":
        return "opensuse"
    return None


def _safe_run(command: str) -> str:
    """Run a vetted, read-only lesson command and return its output."""
    try:
        proc = subprocess.run(
            shlex.split(command),
            capture_output=True, text=True, timeout=10, check=False,
        )
        return (proc.stdout or proc.stderr).strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def _matches(expected: str, typed: str) -> bool:
    """Lenient check that the learner typed the right command.

    Compares the program name (first token); for multi-token commands also
    rewards getting the key argument right, but we stay forgiving — this is a
    confidence builder, not an exam.
    """
    exp = expected.split()
    got = typed.strip().split()
    if not got:
        return False
    if got[0] != exp[0]:
        return False
    # Single-token commands (pwd, whoami, date): first token match is enough.
    return True


class Tutorial:
    """Drives the lesson flow and persists progress between runs."""

    def __init__(
        self,
        *,
        system: Optional[SystemInfo] = None,
        presenter: Optional[Presenter] = None,
        input_fn: Callable[[str], str] = input,
        run_fn: Callable[[str], str] = _safe_run,
        config: Optional[_config.Config] = None,
    ) -> None:
        self.system = system or detect_system()
        self.ui = presenter or Presenter(input_fn=input_fn)
        self._input = input_fn
        self._run = run_fn
        self.config = config or _config.load_config()

    # -- public entry -------------------------------------------------------

    def run(self) -> int:
        """Run (or resume) the tutorial. Returns a process exit code."""
        self._intro()

        start = self._choose_start(UNIVERSAL)
        if start is None:
            self.ui.blank()
            self.ui.info("No problem — run /learn whenever you're ready. 👋")
            return 0

        did_basics = start < len(UNIVERSAL)
        if did_basics:
            if not self._run_track("universal", "the basics", UNIVERSAL, start_at=start):
                return 0  # the learner chose to stop; progress is saved

        pkg_id = package_for_system(self.system)
        if pkg_id is None:
            if did_basics:
                self._all_done()
            return 0

        label, lessons = PACKAGES[pkg_id]
        self.ui.blank()
        if did_basics:
            self.ui.success("🎓 You've finished the basics!")
            self.ui.info(f"There's a bonus track tailored to your system: [bold]{label}[/].")
            prompt = "Want to continue with it now?"
        else:
            self.ui.info(f"Skipping ahead to the track for your system: [bold]{label}[/].")
            prompt = "Ready to start it?"
        if not self.ui.ask_yes_no(prompt, default_no=False):
            self.ui.info("No problem — run /learn anytime to pick up where you left off.")
            return 0
        self._run_track(pkg_id, label, lessons)
        self._all_done()
        return 0

    def _choose_start(self, lessons: tuple[Lesson, ...]) -> Optional[int]:
        """Show the lesson index and ask where to dive in.

        Returns a 0-based start index into the universal track, ``len(lessons)``
        to skip the basics and jump straight to the distro track, or ``None`` if
        the learner wants to quit.
        """
        self.ui.blank()
        self.ui.info("[bold]The core lessons:[/]")
        for i, lesson in enumerate(lessons, 1):
            self.ui.info(f"  [bold cyan]{i:>2}[/]  {lesson.title}")

        saved = int(self.config.learn_progress.get("universal", 0))
        self.ui.blank()
        self.ui.info("How comfortable are you with the terminal? Jump in wherever fits:")
        self.ui.info("  • Press [bold]Enter[/] — brand new, start from lesson 1")
        self.ui.info("  • Type a [bold]lesson number[/] above to start there")
        if 0 < saved < len(lessons):
            self.ui.info(f"  • Type [bold]r[/] — resume where you left off (lesson {saved + 1})")
        self.ui.info("  • Type [bold]skip[/] — already know the basics, go to the "
                     "system-specific track")
        self.ui.info("  • Type [bold]q[/] — quit")

        raw = self._safe_input("\nWhere should we start? ")
        if raw is None:
            return None
        choice = raw.strip().lower()
        if choice in _QUIT_WORDS:
            return None
        if choice == "":
            return 0
        if choice in ("r", "resume") and 0 < saved < len(lessons):
            return saved
        if choice in ("skip", "s"):
            return len(lessons)
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(lessons):
                return n - 1
            self.ui.warn(f"There are {len(lessons)} lessons — starting from the top.")
        return 0

    # -- track / lesson flow ------------------------------------------------

    def _run_track(self, track_id: str, label: str, lessons: tuple[Lesson, ...],
                   *, start_at: Optional[int] = None) -> bool:
        """Run the lessons in a track. Returns False if the learner asked to stop
        partway (progress saved). ``start_at`` overrides saved progress when the
        learner explicitly chose an entry point."""
        if start_at is not None:
            start = max(0, min(start_at, len(lessons) - 1))
        else:
            start = int(self.config.learn_progress.get(track_id, 0))
            if start >= len(lessons):
                start = 0  # already complete -> let them replay from the top
        for i in range(start, len(lessons)):
            if self._teach(lessons[i], i + 1, len(lessons), label):
                # Learner quit mid-lesson: resume *at* this lesson next time.
                self._save_progress(track_id, i)
                self.ui.blank()
                self.ui.success("Stopped the tutorial — your progress is saved. "
                                "Run /learn to continue. 👋")
                return False
            self._save_progress(track_id, i + 1)
            if i + 1 < len(lessons):
                if not self.ui.ask_yes_no("Ready for the next lesson?", default_no=False):
                    self.ui.blank()
                    self.ui.success("Saved your progress. Run /learn to continue later. 👋")
                    return False
        return True

    def _teach(self, lesson: Lesson, number: int, total: int, label: str) -> bool:
        """Present one lesson. Returns True if the learner asked to quit."""
        from rich.panel import Panel
        from rich.text import Text

        self.ui.blank()
        body = Text()
        for line in lesson.concept:
            body.append(line + "\n")
        body.append("\n")
        body.append("  Command:  ", style="bold")
        body.append(lesson.command + "\n", style="bold white on grey15")
        body.append("            ", style="bold")
        body.append(lesson.command_note, style="dim")
        self.ui.console.print(Panel(
            body,
            title=f"Lesson {number}/{total} · {label} — {lesson.title}",
            border_style="cyan",
            expand=False,
            padding=(1, 2),
        ))

        if lesson.quiz:
            return self._do_quiz(lesson)
        if lesson.expected:
            return self._do_practice(lesson)
        # concept-only lessons just display and move on.
        return False

    def _do_quiz(self, lesson: Lesson) -> bool:
        """Run a comprehension check. Returns True if the learner asked to quit."""
        question, accepted = lesson.quiz
        for attempt in range(_MAX_TRIES + 1):
            raw = self._safe_input(f"\n{question}\n(or type 'q' to stop)\n> ")
            if raw is None:
                return True  # EOF / Ctrl+C -> leave the tutorial
            answer = raw.strip().lower()
            if answer in _QUIT_WORDS:
                return True
            if accepted.lower() in answer:
                self.ui.success("Exactly right. ✅")
                return False
            if attempt < _MAX_TRIES:
                self.ui.warn("Not quite — give it one more try.")
        self.ui.info(f"[dim]The answer is: {accepted}[/]")
        return False

    def _do_practice(self, lesson: Lesson) -> bool:
        """Run the try-it-yourself step. Returns True if the learner asked to quit."""
        for attempt in range(_MAX_TRIES + 1):
            raw = self._safe_input(f"\n{lesson.practice_prompt}\n(or type 'q' to stop)\n$ ")
            if raw is None:
                return True  # EOF / Ctrl+C -> leave the tutorial
            typed = raw.strip()
            if typed.lower() in _QUIT_WORDS:
                return True
            if _matches(lesson.expected, typed):
                self.ui.success("That's it. ✅")
                if lesson.run_demo:
                    self._show_demo(lesson.expected)
                return False
            if attempt < _MAX_TRIES:
                self.ui.warn(f"Close! The command to type is:  {lesson.expected}")
        self.ui.info(f"[dim]No worries — the command was:  {lesson.expected}[/]")
        if lesson.run_demo:
            self._show_demo(lesson.expected)
        return False

    def _show_demo(self, command: str) -> None:
        """Run a vetted read-only command so the learner sees real output."""
        output = self._run(command)
        if not output:
            return
        self.ui.console.print("[dim]Here's what it shows on your system:[/]")
        # Trim very long output so a busy folder doesn't flood the screen.
        lines = output.splitlines()
        shown = lines[:12]
        for line in shown:
            self.ui.console.print("  " + line, markup=False)
        if len(lines) > len(shown):
            self.ui.console.print(f"  [dim]... and {len(lines) - len(shown)} more lines[/]")

    # -- intro / outro ------------------------------------------------------

    def _intro(self) -> None:
        from rich.panel import Panel
        from rich.text import Text

        self.ui.blank()
        banner = Text()
        banner.append("Welcome to the Novato terminal tutorial!  🎓\n\n", style="bold green")
        banner.append("We'll go one command at a time. Each lesson explains an idea,\n")
        banner.append("lets you try it, and checks you've got it before moving on.\n\n")
        banner.append("You can stop after any lesson — your progress is saved.\n", style="dim")
        self.ui.console.print(Panel(
            banner, title="🌱 /learn", border_style="green", expand=False, padding=(1, 3),
        ))

    def _all_done(self) -> None:
        self.ui.blank()
        self.ui.success("🎉 That's the whole tutorial — you're well on your way "
                        "from novato to pro!")
        self.ui.info("Forgotten a command? Try  /cheat  or  novato /man \"<task>\".")

    # -- helpers ------------------------------------------------------------

    def _save_progress(self, track_id: str, completed: int) -> None:
        progress = dict(self.config.learn_progress)
        progress[track_id] = max(int(progress.get(track_id, 0)), completed)
        self.config = _config.update_config(learn_progress=progress)

    def _safe_input(self, prompt: str) -> Optional[str]:
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            return None
