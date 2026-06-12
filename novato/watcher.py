# SPDX-License-Identifier: GPL-3.0-or-later
"""Silent error watcher (`/mistake`).

Two responsibilities:

1. **Shell integration** — install/remove a small hook in the user's shell rc
   file (``~/.zshrc`` or ``~/.bashrc``). The hook runs after every command and,
   *only* on a non-zero exit, pipes the failed command + its exit code to
   ``novato --analyze-error``. While commands succeed, Novato is invisible.

2. **Diagnosis** — delegate the actual analysis to the backend chain
   (AI tiers → Basic-mode rule engine). That logic lives in
   :mod:`novato.rules` / the router; this module owns the hook lifecycle.

The hook is wrapped in clearly-marked ``# >>> novato`` / ``# <<< novato`` guards
so it can be added and removed idempotently without disturbing the rest of the
user's config.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

BEGIN_MARKER = "# >>> novato mistake hook >>>"
END_MARKER = "# <<< novato mistake hook <<<"

# zsh: precmd runs before each prompt; $? there is the last command's status.
# The exported marker lets Novato detect whether *this* shell already loaded the
# hook, so it only nags about activation when the hook genuinely isn't live.
# Exit codes >= 128 mean the command was killed by a signal (130 = Ctrl+C,
# 143 = SIGTERM): the user stopped it on purpose, so that's not a mistake.
_ZSH_HOOK = f"""{BEGIN_MARKER}
# Catches failed commands and asks Novato to explain them. Remove with:
#   novato /mistake off
export NOVATO_MISTAKE_ACTIVE=1
novato_mistake_handler() {{
    local exit_code=$?
    if [ $exit_code -ne 0 ] && [ $exit_code -lt 128 ]; then
        local last_cmd
        last_cmd=$(fc -ln -1 2>/dev/null)
        [ -n "$last_cmd" ] && command novato --analyze-error "$last_cmd" "$exit_code" </dev/null
    fi
}}
typeset -ga precmd_functions
precmd_functions+=(novato_mistake_handler)
{END_MARKER}"""

# bash: PROMPT_COMMAND runs before each prompt; capture $? first.
_BASH_HOOK = f"""{BEGIN_MARKER}
# Catches failed commands and asks Novato to explain them. Remove with:
#   novato /mistake off
export NOVATO_MISTAKE_ACTIVE=1
novato_mistake_handler() {{
    local exit_code=$?
    if [ $exit_code -ne 0 ] && [ $exit_code -lt 128 ]; then
        local last_cmd
        last_cmd=$(history 1 | sed 's/^ *[0-9]* *//')
        [ -n "$last_cmd" ] && command novato --analyze-error "$last_cmd" "$exit_code" </dev/null
    fi
}}
case "$PROMPT_COMMAND" in
    *novato_mistake_handler*) ;;
    *) PROMPT_COMMAND="novato_mistake_handler${{PROMPT_COMMAND:+; $PROMPT_COMMAND}}" ;;
esac
{END_MARKER}"""

_HOOKS = {"zsh": _ZSH_HOOK, "bash": _BASH_HOOK}
_RC_FILES = {"zsh": "~/.zshrc", "bash": "~/.bashrc"}


def supported_shell(shell: str) -> bool:
    """True if we can install a hook for this shell."""
    return shell in _HOOKS


def rc_path(shell: str) -> Optional[Path]:
    """Return the rc file path for ``shell`` (honouring ``$HOME``)."""
    rc = _RC_FILES.get(shell)
    return Path(os.path.expanduser(rc)) if rc else None


def hook_snippet(shell: str) -> str:
    """Return the hook text for ``shell`` (empty string if unsupported)."""
    return _HOOKS.get(shell, "")


def is_installed(shell: str, *, rc_file: Optional[Path] = None) -> bool:
    """True if the Novato hook is present in the shell's rc file."""
    path = rc_file or rc_path(shell)
    if path is None or not path.exists():
        return False
    try:
        return BEGIN_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def install_hook(shell: str, *, rc_file: Optional[Path] = None) -> tuple[bool, str]:
    """Install (or upgrade) the watcher hook in the shell rc file (idempotent).

    Returns ``(changed, message)``. ``changed`` is False if the current hook
    version was already present or the shell is unsupported. An *outdated*
    marked block (from an older Novato) is replaced in place, so hook fixes
    reach machines that installed the hook long ago.
    """
    if not supported_shell(shell):
        return False, f"Shell '{shell}' isn't supported for the /mistake hook yet."
    path = rc_file or rc_path(shell)
    if path is None:
        return False, "Could not locate your shell config file."

    upgraded = False
    if is_installed(shell, rc_file=path):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, f"Couldn't read {path}: {exc}"
        if hook_snippet(shell) in content:
            return False, f"The /mistake hook is already installed in {path}."
        # An older hook version is present: strip it and re-append the current one.
        try:
            path.write_text(_strip_block(content), encoding="utf-8")
        except OSError as exc:
            return False, f"Couldn't update {path}: {exc}"
        upgraded = True

    snippet = "\n\n" + hook_snippet(shell) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(snippet)
    except OSError as exc:
        return False, f"Couldn't write to {path}: {exc}"
    verb = "Updated" if upgraded else "Installed"
    return True, (
        f"{verb} the /mistake hook in {path}. "
        f"Run 'source {path}' or restart your terminal to activate it."
    )


def uninstall_hook(shell: str, *, rc_file: Optional[Path] = None) -> tuple[bool, str]:
    """Remove the watcher hook from the shell rc file (idempotent).

    Returns ``(changed, message)``.
    """
    path = rc_file or rc_path(shell)
    if path is None or not path.exists():
        return False, "Nothing to remove — no shell config file found."
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Couldn't read {path}: {exc}"
    if BEGIN_MARKER not in content:
        return False, f"The /mistake hook isn't installed in {path}."

    cleaned = _strip_block(content)
    try:
        path.write_text(cleaned, encoding="utf-8")
    except OSError as exc:
        return False, f"Couldn't update {path}: {exc}"
    return True, f"Removed the /mistake hook from {path}."


def _strip_block(content: str) -> str:
    """Remove the marked hook block (and surrounding blank lines) from text."""
    lines = content.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == BEGIN_MARKER:
            skipping = True
            # Drop a single trailing blank line we added before the block.
            while out and out[-1].strip() == "":
                out.pop()
            continue
        if line.strip() == END_MARKER:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    result = "\n".join(out)
    return result + "\n" if content.endswith("\n") else result
