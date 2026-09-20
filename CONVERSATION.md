# Novato — Context & Design Rationale

This file captures *why* Novato exists and how its design was reached, so future
contributors understand the decisions rather than just the code.

---

## The original idea

A natural-language terminal companion for Linux. A beginner shouldn't have to
already know that "a video player" is `vlc`, that Arch uses `pacman` while Ubuntu
uses `apt`, or that the AUR even exists. They should be able to say what they
*want* and have the machine bridge the gap — while never giving up the power and
transparency that make Linux worth using.

## What was researched

Existing tools were evaluated and each fell short of the goal:

| Tool | Gap |
|---|---|
| Shell-GPT (`sgpt`) | Not distro-aware, not repo-aware, needs a paid API |
| Open Interpreter | Too broad/heavy, not install-focused |
| Warp Terminal | Proprietary, replaces the whole terminal, no offline, not FOSS |
| Claude Code / Gemini CLI | General agents, no AUR/apt intent search |
| `nl-sh` | Generic, no distro awareness, no teaching |
| GUI package wrappers | No AI, no NL, no teaching — just buttons |
| `thefuck` | Fixes the last command only; no teaching, no installer, no NL |

**The unfilled gap:** one lightweight FOSS tool combining intent-based discovery,
distro-aware PM selection, an always-ready silent error watcher, passive
teaching, full offline operation, and zero prior setup — buildable into a distro
as a default feature. That is Novato.

## How the idea evolved

- It began as an **Ubuntu** helper, then **Arch** (where the AUR makes intent
  search most valuable), and finally settled on **distro-agnostic** — detect the
  system, never hardcode. `ID_LIKE` fallback means most derivatives work for
  free.
- Three features crystallised: **NLPM** (install by intent), **`/mistake`**
  (silent error watcher), and **`/explain`** (teaching mode) — chosen because
  they map exactly to the three pain points beginners hit: *finding*, *failing*,
  and *learning*.

## Backend decisions

- **llamafile over Ollama (offline):** a single self-contained binary, no daemon
  eating RAM in the background, and distributable inside Novato itself.
- **Groq for online:** LPU hardware gives ~200 ms latency and 700+ tokens/s,
  with a genuinely free tier (no credit card). Crucially, only the *intent* is
  ever sent — never the user's commands or system details.
- **Basic mode is the bedrock:** difflib + rules + a static intent map. It is the
  permanent fallback so Novato can never hard-fail, and it satisfies the
  "offline first / privacy first / works on 4 GB RAM" constraints alone.
- **"Both" mode is highly recommended:** Groq primary with llamafile fallback —
  fast when online, private when offline, never broken.

## Tooling decision (build-time)

Packaging uses **uv + `pyproject.toml`** (hatchling backend) rather than the
classic `setup.py`/`requirements.txt`. It is faster, reproducible, and a single
source of truth — chosen during Phase 1 at the maintainer's request.

## The name

**Novato** means "beginner / newcomer" in Spanish and Portuguese. It names the
audience with respect rather than condescension, and the tagline closes the loop:

> **From novato to pro.**

The mission: make Linux terminals human — accessible to every person on Earth —
without dumbing down the power Linux offers. The north star is to be proposed as
a **default feature** in Arch and Ubuntu.
