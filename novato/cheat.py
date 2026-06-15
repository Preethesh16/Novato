# SPDX-License-Identifier: GPL-3.0-or-later
"""Instant command cheat-sheets (`/cheat`).

A beginner's fastest path from "I'm stuck" to "oh, that's the command" is a
short, curated reference grouped by topic — no AI, no network, no waiting.

Each category is a flat list of ``(command, plain-English description)`` pairs.
The data lives here (pure, testable); the presenter renders it as a rich table.
This is intentionally a *small* curated set, not a man-page dump: the goal is
the handful of commands a newcomer actually reaches for, in plain words.
"""

from __future__ import annotations

# Category -> ordered list of (command, what it does). Keep entries short and
# beginner-facing; this is reference material, not a tutorial.
CHEATSHEETS: dict[str, list[tuple[str, str]]] = {
    "navigation": [
        ("pwd", "show which folder you're in right now"),
        ("ls", "list the files here"),
        ("ls -la", "list everything, including hidden files, with details"),
        ("cd foldername", "move into a folder"),
        ("cd ..", "go up one folder"),
        ("cd ~", "go to your home folder"),
        ("clear", "wipe the screen clean (or press Ctrl+L)"),
    ],
    "files": [
        ("touch file.txt", "create a new empty file"),
        ("mkdir myfolder", "create a new folder"),
        ("mkdir -p a/b/c", "create nested folders in one go"),
        ("cp file.txt backup.txt", "copy a file"),
        ("cp -r folder/ backup/", "copy a whole folder"),
        ("mv old.txt new.txt", "rename or move a file"),
        ("cat file.txt", "print a file to the screen"),
        ("less file.txt", "scroll through a long file (press q to quit)"),
        ("nano file.txt", "edit a file (save: Ctrl+O, exit: Ctrl+X)"),
        ("rm file.txt", "delete a file — careful, there's no undo!"),
    ],
    "permissions": [
        ("chmod +x script.sh", "make a script runnable"),
        ("./script.sh", "run a script in this folder"),
        ("sudo command", "run a command as administrator"),
        ("chown $USER file", "take ownership of a file (with sudo)"),
        ("ls -la", "see permissions in the first column"),
    ],
    "processes": [
        ("ps aux", "list every running program"),
        ("top", "watch live CPU/memory use (press q to quit)"),
        ("kill 1234", "stop a program by its process number (PID)"),
        ("killall firefox", "stop every process with that name"),
        ("Ctrl+C", "stop the command running right now"),
    ],
    "network": [
        ("ping google.com", "check your internet (Ctrl+C to stop)"),
        ("ip addr", "show your network addresses"),
        ("wget URL", "download a file from the web"),
        ("curl URL", "fetch a web address and print it"),
        ("ssh user@server", "log into another computer"),
    ],
    "text": [
        ('grep "word" file', "find a word inside a file"),
        ('grep -r "word" .', "find a word in every file here and below"),
        ("head file", "show the first lines of a file"),
        ("tail file", "show the last lines of a file"),
        ("tail -f log", "watch a file update live (Ctrl+C to stop)"),
        ("wc -l file", "count the lines in a file"),
    ],
    "archives": [
        ("unzip file.zip", "unpack a .zip file"),
        ("zip -r out.zip folder/", "bundle a folder into a .zip"),
        ("tar -xzf file.tar.gz", "unpack a .tar.gz file"),
        ("tar -czf out.tar.gz folder/", "bundle a folder into a .tar.gz"),
    ],
    "shortcuts": [
        ("Tab", "auto-complete a file or command name"),
        ("↑ / ↓", "scroll through your previous commands"),
        ("Ctrl+R", "search your command history (type part of it)"),
        ("Ctrl+C", "stop the running command"),
        ("Ctrl+L", "clear the screen"),
        ("Ctrl+Shift+C", "copy selected text (NOT Ctrl+C!)"),
        ("Ctrl+Shift+V", "paste into the terminal"),
    ],
}

# A friendly one-line summary per category, shown as the table's subtitle.
CATEGORY_BLURBS: dict[str, str] = {
    "navigation": "moving around folders",
    "files": "creating, copying, and deleting",
    "permissions": "running things and ownership",
    "processes": "programs that are running",
    "network": "internet and remote machines",
    "text": "searching and reading text",
    "archives": "zip and tar files",
    "shortcuts": "keyboard tricks that save hours",
}


def categories() -> list[str]:
    """Return the available cheat-sheet category names, in display order."""
    return list(CHEATSHEETS)


def get(category: str) -> list[tuple[str, str]]:
    """Return the (command, description) rows for a category, or an empty list."""
    return CHEATSHEETS.get(category.strip().lower(), [])


def resolve_category(arg: str) -> str | None:
    """Map a user's (possibly partial) word to a real category name.

    Accepts prefixes and a few friendly synonyms so ``/cheat nav`` or
    ``/cheat keyboard`` land on the right sheet. Returns ``None`` if unsure.
    """
    arg = arg.strip().lower()
    if not arg:
        return None
    synonyms = {
        "nav": "navigation", "dir": "navigation", "folder": "navigation",
        "file": "files", "perm": "permissions", "permission": "permissions",
        "sudo": "permissions", "proc": "processes", "process": "processes",
        "net": "network", "internet": "network", "search": "text",
        "grep": "text", "archive": "archives", "zip": "archives",
        "tar": "archives", "shortcut": "shortcuts", "keyboard": "shortcuts",
        "keys": "shortcuts", "key": "shortcuts",
    }
    if arg in CHEATSHEETS:
        return arg
    if arg in synonyms:
        return synonyms[arg]
    matches = [c for c in CHEATSHEETS if c.startswith(arg)]
    return matches[0] if len(matches) == 1 else None
