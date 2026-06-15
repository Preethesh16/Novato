# Novato — Technical Documentation

This document is the deep reference for Novato's architecture, internals, and
extension points. For a quick tour, see [README.md](README.md).

---

## Table of contents

1. [Architecture](#architecture)
2. [The three features](#the-three-features)
3. [AI backend system](#ai-backend-system)
4. [Distro support](#distro-support)
5. [Safety rules](#safety-rules)
6. [Configuration file format](#configuration-file-format)
7. [History log format](#history-log-format)
8. [Privacy](#privacy)
9. [Extending Novato](#extending-novato)
10. [Proposing Novato as a default distro feature](#proposing-novato-as-a-default-distro-feature)

---

## Architecture

Novato is a small, layered Python application. Each module has a single
responsibility and is independently testable.

```text
                         ┌──────────────┐
        user input  ───▶ │   main.py    │  CLI entry / slash-command routing
                         └──────┬───────┘
                                │
        ┌───────────────────────┼─────────────────────────────┐
        ▼                       ▼                              ▼
  ┌───────────┐          ┌─────────────┐                ┌────────────┐
  │ detector  │          │   intent    │                │  watcher   │  /mistake
  │ distro/PM │          │ NL parsing  │                │  teacher   │  /explain
  └─────┬─────┘          └──────┬──────┘                │  switcher  │  /switch
        │                       ▼                       └─────┬──────┘
        │              ┌─────────────────┐                    │
        │              │ backends/router │ ◀── fallback chain  │
        │              └────────┬────────┘                    │
        │        ┌──────────────┼──────────────┐              │
        │        ▼              ▼              ▼               │
        │   groq_backend  llamafile_backend  basic_backend     │
        │                                    (rules+intent_map)│
        ▼                                                      ▼
  ┌───────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  ┌──────────┐
  │ searcher  │──▶│  ranker  │──▶│presenter │──▶│  safety  │─▶│ executor │
  │ AUR/apt.. │   │ relevance│   │ rich UI  │   │  gate    │  │ live out │
  └───────────┘   └──────────┘   └──────────┘   └──────────┘  └─────┬────┘
                                                                    ▼
                                                            ┌──────────────┐
                                                            │ logger        │
                                                            │ history.log   │
                                                            └──────────────┘
```

**Module responsibilities**

| Module | Responsibility |
|---|---|
| `detector.py` | Detect distro, package manager, AUR helper, shell. |
| `config.py` | Read/write `~/.novato/config.json` (atomic, 0600). |
| `logger.py` | Append every executed command to `history.log`. |
| `intent_map.py` | Static intent → package candidates (Basic mode). |
| `rules.py` | Hardcoded error-correction rules (the `/mistake` brain). |
| `safety.py` | Confirmation gate + destructive-command blocker. |
| `backends/basic_backend.py` | difflib + rules + intent map. Always works. |
| `backends/llamafile_backend.py` | Local offline LLM (llamafile). |
| `backends/groq_backend.py` | Online Groq inference. |
| `backends/router.py` | Fallback chain online → offline → basic. |
| `searcher.py` | Search AUR / apt-cache / pacman / dnf / zypper. |
| `ranker.py` | Rank search results by relevance. |
| `presenter.py` | Rich terminal UI + status badges. |
| `executor.py` | Run commands with live output streaming. |
| `setup_wizard.py` | First-run onboarding flow. |
| `downloader.py` | Offline-model registry + resumable llamafile download. |
| `watcher.py` | `/mistake` shell-hook lifecycle (zsh/bash). |
| `teacher.py` | `/explain` command glossary (installs + any command). |
| `switcher.py` | `/switch` AI-mode management. |
| `howto.py` | Task → single-command knowledge base (`/do`, `/man`, NLPM tasks). |
| `cheat.py` | Static command cheat-sheets (`/cheat`). |
| `sysinfo.py` | Disk + process inspection helpers (`/disk`, `/process`). |
| `learner.py` | Interactive, distro-aware tutorial engine (`/learn`). |

---

## The three features

### 1. NLPM — Natural Language Package Manager

Flow: *intent → keywords → repo search → rank → present → confirm → execute*.

In **Basic mode**, intent resolution is pure `difflib`/token-overlap matching
against `INTENT_MAP` — no network, no AI. Smarter tiers replace the
keyword-extraction and ranking steps but never the safety gate.

### 2. `/mistake` — silent error watcher

A shell hook runs after every command and, *only* on a non-zero exit, calls
`novato --analyze-error`. The rule engine (`rules.py`) produces a beginner
friendly diagnosis and an optional fix, which the user can run after confirming.
It is completely invisible while commands succeed.

### 3. `/explain` — teaching mode

When enabled, every Novato action is accompanied by a short, respectful,
plain-English explanation of the command and its flags. Explanations appear
*after* the action description and never block it.

---

## AI backend system

Three tiers behind one interface, wired by `backends/router.py`:

| Tier | Engine | Speed | RAM | Privacy |
|---|---|---|---|---|
| Basic | difflib + rules + intent map | ms | ~5 MB | 100% local |
| Offline | llamafile (Mozilla) | 3–8 s | 2–4 GB | 100% local |
| Online | Groq free API | ~200 ms | ~5 MB | query only |

**Fallback chain**: online → offline → basic. If every smarter tier is
unavailable, Basic mode always answers, so Novato never hard-fails.

### Why these choices

- **Groq over OpenAI/Ollama for online**: Groq's LPU hardware delivers
  700+ tokens/s, a genuinely free tier (no credit card), and ~200 ms latency.
- **llamafile over Ollama for offline**: a single self-contained binary with no
  background daemon eating RAM, and it can be distributed with Novato itself.

### llamafile model selection (by RAM)

Novato auto-selects an official Mozilla llamafile sized for the machine's RAM
and downloads it (resumable, with a progress bar) into `~/.novato/engine/`. See
[`downloader.py`](novato/downloader.py).

| Total RAM | Model | Size |
|---|---|---|
| < 4 GB | TinyLlama 1.1B Chat | ~1.0 GB |
| < 8 GB | Phi-3-mini 4k Instruct | ~2.4 GB |
| < 16 GB | Mistral-7B Instruct v0.3 | ~4.7 GB |
| ≥ 16 GB | Llama 3.1 8B Instruct | ~5.2 GB |

Download it any time:

```bash
novato --download-model            # auto-select by RAM, then enable offline mode
novato --download-model phi3-mini  # pick a specific model
```

The download is **resumable** (a partial `.part` file is continued with an HTTP
`Range` request) and **atomic** (it is moved into place and `chmod +x`'d only on
success), so an interrupted multi-GB download never looks complete or corrupts
the engine directory.

---

## Distro support

Detection reads `/etc/os-release` (via the `distro` library, with a pure-stdlib
fallback) and maps the `ID` to a package manager. Unknown derivatives fall back
through their `ID_LIKE` family tokens, so most remixes work without a code
change.

| Family | `ID` examples | PM | Install | AUR |
|---|---|---|---|---|
| Arch | `arch`, `manjaro`, `endeavouros`, `garuda`, `artix` | `pacman` | `sudo pacman -S` | ✅ |
| Debian | `debian`, `ubuntu`, `linuxmint`, `pop`, `elementary`, `zorin`, `kali` | `apt` | `sudo apt install` | — |
| Fedora | `fedora`, `rhel`, `centos`, `rocky`, `almalinux` | `dnf` | `sudo dnf install` | — |
| openSUSE | `opensuse*`, `sles` | `zypper` | `sudo zypper install` | — |

See `DISTRO_PM_MAP` in [`detector.py`](novato/detector.py).

---

## Safety rules

These are **absolute and non-negotiable**, enforced primarily by
[`safety.py`](novato/safety.py):

1. Never auto-execute. Always show the command, always ask `y/N`.
2. Never emit `--noconfirm`, `-y`, or `--yes` — they are stripped from any
   generated command (`safety.sanitize`).
3. Never suggest or run `rm`, `dd`, `mkfs`, `fdisk`, … — these are *blocked*
   (`safety.validate` returns `Risk.BLOCKED`).
4. Never send actual commands to Groq — only the intent/query.
5. Never send file paths, usernames, or system info to any online service.
6. Always log every executed command to `~/.novato/history.log`.
7. Always respect `--dry-run` — `safety.confirm` returns `False` in dry-run.
8. When unsure about safety, refuse and explain why.

---

## Configuration file format

`~/.novato/config.json` (mode `0600`, atomic writes):

```json
{
  "mode": "both",
  "explain": false,
  "mistake": true,
  "groq_api_key": "gsk_...",
  "groq_model": "llama-3.3-70b-versatile",
  "llamafile_path": "/home/user/.novato/engine/phi3.llamafile",
  "llamafile_model": "phi3",
  "setup_complete": true,
  "version": 1
}
```

Override the directory with `NOVATO_HOME` (used in tests and for portable
installs). A corrupt config never crashes Novato — it falls back to defaults.

---

## History log format

`~/.novato/history.log` — append-only, tab-separated, greppable:

```text
2026-06-10T14:03:21+05:30   EXEC      sudo pacman -S shotcut
2026-06-10T14:05:02+05:30   DRYRUN    sudo apt install vlc
2026-06-10T14:06:10+05:30   FIX       sudo pacman -S vlc    # /mistake fix
```

Event kinds: `EXEC`, `DRYRUN`, `FIX`, `DECLINE`, `SEARCH`.

---

## Privacy

- **Basic** and **Offline** modes send nothing off the machine, ever.
- **Online** mode sends *only the intent text you type* (e.g. "edit videos") to
  Groq. It never sends your actual commands, file paths, usernames, hostname,
  environment, or history.
- The Groq API key lives only in your local `config.json` (mode `0600`).

---

## Extending Novato

### Add a new intent

Edit [`intent_map.py`](novato/intent_map.py). Add a lowercase key and an ordered
list of candidate packages (most beginner-friendly first), using Arch/AUR
naming as the canonical form:

```python
"edit subtitles": ["subtitleeditor", "gnome-subtitles"],
```

Run `uv run pytest tests/test_intent.py`.

### Add a new error rule

Edit [`rules.py`](novato/rules.py). Add a function decorated with `@rule` that
returns a `Correction` on match or `None` otherwise. Rules are tried in
registration order; the first confident match wins. Keep explanations
beginner-level and never propose a destructive fix.

```python
@rule
def my_rule(ctx: ErrorContext) -> Optional[Correction]:
    if "some signature in stderr" not in ctx.stderr.lower():
        return None
    return Correction(title="…", reason="…", fix="…", confidence=0.7,
                      rule_name="my_rule")
```

Add a test in `tests/test_watcher.py`.

### Add a new "how-to" task

Edit [`howto.py`](novato/howto.py). Append a `HowtoEntry` to `_ENTRIES` with the
phrasings a user might type, a command template (use a single `{arg}` for a
fillable filename and set `default_arg`), a one-line explanation, and a
category:

```python
HowtoEntry(("watch a folder for changes", "monitor a folder"),
           "inotifywait -m {arg}", "watch a folder for file changes",
           "files", default_arg="foldername"),
```

Mark `dangerous=True` for anything that deletes/overwrites — such tasks are shown
for reference and never auto-run. Run `uv run pytest tests/test_howto.py`.

### Add a `/learn` lesson

Edit [`learner.py`](novato/learner.py). Append a `Lesson` to `UNIVERSAL` (or a
distro package). Use `expected`/`run_demo` for a hands-on, vetted read-only
command, or `quiz=(question, accepted_substring)` for a comprehension check.
Never run a destructive command in a lesson. Run `uv run pytest
tests/test_learner.py`.

### Add a new distro

Add an entry to `DISTRO_PM_MAP` in [`detector.py`](novato/detector.py) keyed by
its `/etc/os-release` `ID`. If it is a derivative of an existing family,
`ID_LIKE` may already cover it — add a test in `tests/test_detector.py` to
confirm.

---

## Proposing Novato as a default distro feature

**Arch Linux**

1. Submit a `PKGBUILD` to the AUR (open to anyone).
2. Share a demo on r/archlinux and the Arch forums (Community Contributions).
3. With enough AUR votes, propose for the community repository.

**Ubuntu**

1. Publish to PyPI (`pip install novato`).
2. Build a `.deb` package.
3. Post on Ubuntu Discourse (Ideas) and file a blueprint on the Ubuntu Wiki.
4. Engage the Ubuntu Desktop team if traction builds.
