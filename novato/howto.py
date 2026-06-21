# SPDX-License-Identifier: GPL-3.0-or-later
"""Task -> command knowledge base ("how do I ...").

Novato's package flow answers *"what should I install?"*. This module answers a
different, equally beginner-critical question: *"how do I actually do this in the
terminal?"*. A newcomer doesn't know the command name (``tar``, ``mv``,
``unzip``) — they only know the task ("unzip this file", "rename a file"). So
here we map plain-English tasks to a single, simplest-possible command plus a
one-line explanation.

Golden rules (kept deliberately strict so the answer never overwhelms):

* **One command.** No alternatives, no "you could also...".
* **One sentence** of explanation, at most.
* **No flags** unless the task literally requires them.
* **Never auto-run anything dangerous.** Destructive tasks (delete) are shown as
  a teaching note with a warning and are *not* offered for execution; the safety
  layer blocks them regardless.

The module is pure data + a small fuzzy matcher (stdlib only), so it works in
Basic mode with zero AI and is fully unit-testable. Smarter AI tiers can answer
anything this map misses, via the same one-line format in :mod:`teacher`.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Optional

# Sentinel a template uses when the right command depends on the user's distro
# (e.g. "update my system"). :mod:`main` substitutes the detected sync command.
SYNC_SENTINEL = "{SYNC}"

# Words that are never the *argument* of a task (filenames/folders survive).
# Used only when extracting a concrete argument from the user's phrasing.
_ARG_STOP = frozenset({
    "i", "want", "to", "a", "an", "the", "my", "some", "please", "need",
    "would", "like", "can", "you", "help", "me", "how", "do", "in", "on",
    "this", "that", "novato", "with", "of", "for", "and", "is", "it", "from",
    "file", "files", "folder", "folders", "directory", "named", "called",
    "terminal", "command", "here", "there",
})


@dataclass(frozen=True)
class HowtoEntry:
    """One task definition: phrasings -> a single command + explanation."""

    keys: tuple[str, ...]          # phrasings that should match this task
    template: str                  # command; may contain a single ``{arg}``
    explanation: str               # one-line, plain-English description
    category: str
    default_arg: str = ""          # placeholder shown when no arg is given
    note: str = ""                 # optional extra line (e.g. how to stop it)
    dangerous: bool = False        # never auto-runnable; show a warning instead


@dataclass
class HowtoAnswer:
    """A resolved answer: the command to show, and whether it's safe to run."""

    command: str
    explanation: str
    category: str
    note: str = ""
    runnable: bool = True          # False -> show as reference, don't offer to run
    dangerous: bool = False
    placeholder: bool = False      # command contains an example name to swap out
    score: float = 0.0
    matched_key: str = ""

    @property
    def label(self) -> str:
        """The 'To <explanation>:' lead-in shown above the command."""
        return self.explanation


# ---------------------------------------------------------------------------
# The knowledge base. Ordered loosely by how often a beginner reaches for it.
# Keys are short lowercase phrasings; matching is fuzzy so near-misses still hit.
# ---------------------------------------------------------------------------
_ENTRIES: tuple[HowtoEntry, ...] = (
    # -- Navigation ---------------------------------------------------------
    HowtoEntry(("where am i", "current folder", "current directory",
                "which folder am i in", "print working directory"),
               "pwd", "see which folder you're currently in", "navigation"),
    HowtoEntry(("list files", "show files", "whats here", "what is here",
                "see files", "show everything here", "list everything"),
               "ls -la", "list everything in this folder (including hidden files)",
               "navigation"),
    HowtoEntry(("go to folder", "change directory", "open folder",
                "enter folder", "go into folder"),
               "cd {arg}", "move into a folder", "navigation",
               default_arg="foldername"),
    HowtoEntry(("go back", "go up", "parent folder", "go up one level",
                "previous folder"),
               "cd ..", "go up to the folder above", "navigation"),
    HowtoEntry(("go home", "home folder", "go to home"),
               "cd ~", "jump back to your home folder", "navigation"),
    HowtoEntry(("clear screen", "clear terminal", "clean the screen",
                "clear the screen"),
               "clear", "wipe the screen clean", "navigation"),

    # -- Files --------------------------------------------------------------
    HowtoEntry(("create a file", "make a file", "new file", "create file"),
               "touch {arg}", "create a new empty file", "files",
               default_arg="filename.txt"),
    HowtoEntry(("create a folder", "make a folder", "new folder",
                "make a directory", "create directory", "create a directory"),
               "mkdir {arg}", "create a new folder", "files",
               default_arg="myfolder"),
    HowtoEntry(("read a file", "view a file", "show file contents",
                "see whats in a file", "print a file", "open a file in terminal"),
               "cat {arg}", "print a file's contents to the screen", "files",
               default_arg="filename.txt"),
    HowtoEntry(("edit a file", "edit text", "open a file to edit",
                "change a file", "write to a file"),
               "nano {arg}", "open a file in a simple text editor", "files",
               default_arg="filename.txt",
               note="Save with Ctrl+O, then exit with Ctrl+X."),
    HowtoEntry(("rename a file", "rename", "rename file"),
               "mv oldname.txt newname.txt",
               "rename a file (it's the same 'move' command)", "files",
               default_arg="x"),  # multi-arg -> shown for reference only
    HowtoEntry(("copy a file", "copy file", "duplicate a file"),
               "cp file.txt destination/", "copy a file somewhere else", "files",
               default_arg="x"),
    HowtoEntry(("copy a folder", "copy folder", "copy a directory"),
               "cp -r myfolder/ destination/", "copy a whole folder", "files",
               default_arg="x"),
    HowtoEntry(("move a file", "move file", "move folder"),
               "mv thing.txt destination/", "move a file or folder elsewhere",
               "files", default_arg="x"),
    HowtoEntry(("delete a file", "remove a file", "delete file", "remove file"),
               "rm {arg}", "delete a file", "files",
               dangerous=True, default_arg="filename.txt",
               note="There is no Recycle Bin — a deleted file is gone for good."),
    HowtoEntry(("delete a folder", "remove a folder", "delete directory",
                "remove a directory"),
               "rm -r {arg}", "delete a whole folder and its contents",
               "files", dangerous=True, default_arg="foldername",
               note="There is no Recycle Bin — double-check the name first."),

    # -- Archives -----------------------------------------------------------
    HowtoEntry(("unzip", "unzip a file", "extract zip", "open zip",
                "unzip the file", "extract a zip"),
               "unzip {arg}.zip", "unpack a .zip file", "archives",
               default_arg="filename"),
    HowtoEntry(("zip a folder", "compress folder", "make a zip",
                "create a zip", "zip files"),
               "zip -r {arg}.zip foldername/", "bundle a folder into a .zip",
               "archives", default_arg="archive"),
    HowtoEntry(("extract tar", "extract tar gz", "open tar", "untar",
                "extract a tar file"),
               "tar -xzf {arg}.tar.gz", "unpack a .tar.gz file", "archives",
               default_arg="filename"),
    HowtoEntry(("create tar", "make a tar", "compress with tar",
                "create tar gz"),
               "tar -czf archive.tar.gz foldername/",
               "bundle a folder into a .tar.gz", "archives", default_arg="x"),

    # -- Find / search ------------------------------------------------------
    HowtoEntry(("find a file", "search for a file", "locate a file",
                "where is my file", "find file"),
               "find . -name {arg}", "search for a file by name here and below",
               "search", default_arg='"*.txt"'),
    HowtoEntry(("search inside files", "find text in files",
                "search text in files", "grep", "search for words in files"),
               'grep -r "text" .', "search for some text inside every file here",
               "search", default_arg="x"),
    HowtoEntry(("count lines", "how many lines", "line count"),
               "wc -l {arg}", "count the lines in a file", "search",
               default_arg="filename.txt"),
    HowtoEntry(("first lines of a file", "see start of file", "head of file",
                "show first lines"),
               "head {arg}", "show the first few lines of a file", "search",
               default_arg="filename.txt"),
    HowtoEntry(("last lines of a file", "see end of file", "tail of file",
                "show last lines"),
               "tail {arg}", "show the last few lines of a file", "search",
               default_arg="filename.txt"),
    HowtoEntry(("follow a log", "watch a log", "watch a file live",
                "tail a log"),
               "tail -f {arg}", "watch a file update live (great for logs)",
               "search", default_arg="logfile",
               note="Press Ctrl+C to stop watching."),

    # -- Permissions --------------------------------------------------------
    HowtoEntry(("make executable", "make a script runnable",
                "make file executable", "make runnable"),
               "chmod +x {arg}", "let a script be run as a program",
               "permissions", default_arg="script.sh"),
    HowtoEntry(("run a script", "run a shell script", "execute a script"),
               "./{arg}", "run a script in the current folder", "permissions",
               default_arg="script.sh"),
    HowtoEntry(("change owner", "change file owner", "take ownership"),
               "sudo chown $USER filename", "change who owns a file",
               "permissions", default_arg="x"),

    # -- Processes ----------------------------------------------------------
    HowtoEntry(("see running programs", "running processes", "whats running",
                "what is running", "list processes"),
               "ps aux", "list every program currently running", "processes"),
    HowtoEntry(("monitor system", "system monitor", "resource usage",
                "cpu usage", "watch system"),
               "top", "watch live CPU and memory usage", "processes",
               note="Press q to quit."),
    HowtoEntry(("stop a program", "kill a process", "force quit a program",
                "end a process"),
               "kill PID", "stop a stuck program by its process number",
               "processes", default_arg="x",
               note="Find the PID first with 'ps aux'. Or run: novato /process"),

    # -- Disk ---------------------------------------------------------------
    HowtoEntry(("check disk space", "how much space", "disk usage",
                "free disk space", "space left"),
               "df -h", "see how much disk space is free", "disk"),
    HowtoEntry(("folder size", "how big is this folder", "size of a folder",
                "directory size"),
               "du -sh {arg}", "see how much space a folder uses", "disk",
               default_arg="foldername"),

    # -- Network ------------------------------------------------------------
    HowtoEntry(("check internet", "test connection", "am i online",
                "is my internet working", "test internet"),
               "ping google.com", "check whether your internet is working",
               "network", note="Press Ctrl+C to stop."),
    HowtoEntry(("download a file", "download from a url", "fetch a file",
                "grab a file from the web"),
               "wget {arg}", "download a file from a web address", "network",
               default_arg="https://example.com/file"),
    HowtoEntry(("my ip address", "ip address", "whats my ip",
                "show ip address", "network address"),
               "ip addr", "show your computer's network addresses", "network"),
    HowtoEntry(("connect to a server", "ssh into a server", "remote login",
                "ssh"),
               "ssh user@server", "log into another computer over the network",
               "network", default_arg="x"),

    # -- System -------------------------------------------------------------
    HowtoEntry(("update my system", "update everything", "upgrade my system",
                "keep my system updated", "install updates"),
               SYNC_SENTINEL, "refresh and upgrade all your installed software",
               "system"),
    HowtoEntry(("how much ram", "free memory", "memory usage", "check ram"),
               "free -h", "see how much memory (RAM) is free", "system"),
    HowtoEntry(("my username", "whats my username", "who am i"),
               "whoami", "show the name you're logged in as", "system"),
    HowtoEntry(("what time is it", "current date", "what date", "show the date"),
               "date", "show the current date and time", "system"),
)


def _normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, and split a phrase into tokens."""
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return [t for t in text.split() if t]


# Pre-tokenise every key once at import time for fast matching.
_KEY_INDEX: list[tuple[HowtoEntry, str, frozenset[str]]] = [
    (entry, key, frozenset(_normalize(key)))
    for entry in _ENTRIES
    for key in entry.keys
]


def _score(query_tokens: frozenset[str], key: str, key_tokens: frozenset[str]) -> float:
    """Blend token-overlap coverage with a fuzzy string ratio (0..1)."""
    if not key_tokens:
        return 0.0
    overlap = len(query_tokens & key_tokens) / len(key_tokens)
    fuzzy = difflib.SequenceMatcher(
        None, " ".join(sorted(query_tokens)), " ".join(sorted(key_tokens))
    ).ratio()
    # Coverage of the key's words matters most; fuzzy breaks near-ties and
    # rescues typos ("unzipp", "delet a file").
    return round(0.7 * overlap + 0.3 * fuzzy, 3)


def _extract_arg(query: str, key_tokens: frozenset[str]) -> Optional[str]:
    """Pull a concrete argument (a filename/folder) out of the user's phrasing.

    Works on the *raw* tokens (not the normalised ones) so an extension survives
    — "delete report.txt" -> "report.txt", not "report". Prefers a token that
    looks like a filename (has an extension) over a bare word, so "remove my
    report.txt" picks "report.txt". Returns ``None`` for a bare task ("unzip the
    file").
    """
    candidates: list[str] = []
    for raw in query.split():
        # Compare on a normalised form, but keep the original token (with its
        # dots, case, dashes) as the actual argument.
        norm = re.sub(r"[^a-z0-9]", "", raw.lower())
        if not norm or norm in key_tokens or norm in _ARG_STOP:
            continue
        candidates.append(raw.strip("\"'"))
    if not candidates:
        return None
    for tok in candidates:
        if "." in tok.strip("."):          # looks like name.ext
            return tok
    return candidates[0]


def resolve(query: str, *, threshold: float = 0.55) -> Optional[HowtoAnswer]:
    """Match a free-text task to the best :class:`HowtoAnswer`, or ``None``.

    ``threshold`` is the minimum confidence to accept a match. Callers tune it:
    the natural-language flow uses a high bar (so package requests aren't
    hijacked), while the explicit ``/do`` and ``/man`` entry points use a lower
    one (the user already signalled "this is a how-to").
    """
    query = query.strip()
    if not query:
        return None
    q_tokens = frozenset(_normalize(query))
    if not q_tokens:
        return None

    best: Optional[tuple[HowtoEntry, str, float]] = None
    for entry, key, key_tokens in _KEY_INDEX:
        score = _score(q_tokens, key, key_tokens)
        if best is None or score > best[2]:
            best = (entry, key, score)

    if best is None or best[2] < threshold:
        return None

    entry, key, score = best
    return _build_answer(entry, key, score, query)


def _build_answer(entry: HowtoEntry, key: str, score: float, query: str) -> HowtoAnswer:
    """Fill an entry's template with any extracted argument and a runnable flag."""
    command = entry.template
    runnable = True
    placeholder = False

    if "{arg}" in command:
        key_tokens = frozenset(_normalize(key))
        arg = _extract_arg(query, key_tokens)
        if arg:
            # Avoid "report.zip.zip": if the template appends a literal extension
            # right after {arg}, drop any extension the user already typed.
            if "{arg}." in command:
                arg = arg.split(".")[0]
            command = command.format(arg=arg)
        else:
            # No concrete argument given: show a placeholder for reference only,
            # never offer to run a command full of made-up names. This is what
            # keeps a bare "delete a file" from offering to run `rm`.
            command = command.format(arg=entry.default_arg)
            runnable = False
            placeholder = True
    elif entry.default_arg:
        # A multi-argument template (rename/copy/move/ssh ...): always reference.
        runnable = False
        placeholder = True

    if command == SYNC_SENTINEL:
        runnable = False  # main substitutes the real, distro-specific command

    return HowtoAnswer(
        command=command,
        explanation=entry.explanation,
        category=entry.category,
        note=entry.note,
        runnable=runnable,
        dangerous=entry.dangerous,
        placeholder=placeholder,
        score=score,
        matched_key=key,
    )


def all_tasks() -> list[str]:
    """Return every task phrasing (sorted) — handy for tests and docs."""
    return sorted(key for entry in _ENTRIES for key in entry.keys)
