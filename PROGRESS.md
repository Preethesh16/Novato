# Novato Build Progress

## Status: COMPLETE
## Last Updated: 2026-06-10
## Current Prompt: 4 (Phases 4 & 5 — Slash Commands, Packaging)

---

## ✅ Completed

- [x] Project scaffolding (`pyproject.toml` with **uv** + hatchling, `.gitignore`, `LICENSE`)
- [x] Package skeleton (`novato/`, `novato/backends/`, `tests/`)
- [x] `detector.py` — distro + package manager + AUR helper + shell detection, with `ID_LIKE` fallback for derivatives
- [x] `config.py` — typed config, atomic 0600 writes, `NOVATO_HOME` override, corrupt-file resilience
- [x] `logger.py` — append-only history log (`EXEC`/`DRYRUN`/`FIX`/…), newline-flattened, greppable
- [x] `intent_map.py` — **228** curated intents across 14 categories + package descriptions
- [x] `rules.py` — **19** beginner-friendly error-correction rules (typo, wrong PM, missing sudo, py/npm modules, locks, keyring, disk full, ports, …)
- [x] `safety.py` — confirmation gate, destructive-command blocker, auto-confirm-flag stripper, dry-run honoring
- [x] `backends/basic_backend.py` — fuzzy intent resolution (exact → normalized → token-overlap → difflib) + rule-based error analysis
- [x] Documentation: `README.md`, `DOCUMENTATION.md`, `CONVERSATION.md`, this file
- [x] Test suite: **66 tests passing** (`detector`, `safety`, `intent`, `watcher`, `backends`)
- [x] Lint clean (`ruff check novato/`)

### Phase 2 — Core Features ✅
- [x] `searcher.py` — pacman/apt/dnf/zypper parsers + AUR RPC v5 + dedup + `search_candidates`
- [x] `intent.py` — NL front-end producing `IntentPlan` (pluggable backend for Phase 3)
- [x] `ranker.py` — deterministic relevance ranking (curated order > official repo > name match > AUR popularity)
- [x] `presenter.py` — rich UI: status badge, numbered results, EOF-safe prompts, error/explain panels
- [x] `executor.py` — live output streaming, defensive safety re-check, dry-run + pre-exec logging
- [x] `main.py` — CLI entry (`argparse`), NLPM flow, `--analyze-error` hook path, `/status` `/help` `/explain` `/mistake` `/switch`
- [x] End-to-end `novato "install X"` flow **verified live on Arch** (real pacman + AUR search, dry-run)
- [x] Bugfixes: wrong-PM fix dropped the `install` subcommand; prompts now EOF-safe; hook reconnects stdin to `/dev/tty`

### Phase 3 — AI Backends ✅
- [x] `groq_backend.py` — online tier; sends only intent/error text (privacy), JSON-array parsing, destructive-fix stripping, injectable session
- [x] `llamafile_backend.py` — offline tier; RAM-based `select_model`, one-shot CLI inference, injectable runner
- [x] `router.py` — fallback chain (online → offline → basic), graceful degradation, `internet_available` probe, `build_router(config)`
- [x] `setup_wizard.py` — first-run onboarding (mode menu, Groq key verify, model selection), fully injectable for tests
- [x] Wired router into `main.py` (intent + error analysis go through the chain); added `/setup` command
- [x] Fixed `/help` markup so `[online|offline|both|basic]` renders literally

### Phase 4 — Slash Commands ✅
- [x] `teacher.py` — `/explain` engine: command → token glossary (PM meanings + flag glossary), beginner-safe
- [x] `switcher.py` — `/switch` engine: validated mode changes, descriptions, recommended default, menu
- [x] `watcher.py` — `/mistake` engine: **real zsh + bash shell hooks**, idempotent install/remove with marker guards, preserves existing rc config
- [x] Wired into `main.py`: `/mistake on|off` installs/removes the hook; `/explain` uses Teacher; `/switch` shows a menu

### Phase 5 — Polish + Packaging ✅
- [x] Status badges on every status line (`[Novato • <Mode> <emoji>]`)
- [x] `PKGBUILD` for the AUR (python-hatchling build, runs the test suite in check())
- [x] `scripts/install.sh` (pipx/uv/pip, no sudo) + `scripts/uninstall.sh` (removes hook + offers config cleanup)
- [x] Full README with examples, modes, safety, supported distros

## 🔄 In Progress

- [ ] (none — all five phases complete)

## ⏳ Not Started

- [ ] Future: automatic llamafile model download; `.deb` packaging; demo GIF

---

## Notes / decisions
- Switched packaging from `setup.py`/`requirements.txt` to **uv + `pyproject.toml`** (hatchling backend) at the user's request — faster, reproducible, single source of truth.
- Intent map uses Arch/AUR naming as canonical; the searcher (Phase 2) will translate to apt/dnf/zypper equivalents.
- Rule count (19) and intent count (228) exceed the "200+ intents" bar; the rule set is intentionally curated for confidence rather than padded — the AI tiers cover the long tail.

---

## Prompt History

### Prompt 1 — 2026-06-10 — Phase 1: Foundation
**What was built:** Full project scaffolding under **uv**, all foundation modules
(detector, config, logger, intent_map, rules, safety, basic_backend), all four
docs, and a 66-test suite. Everything runs offline with zero AI.
**Files created:** `pyproject.toml`, `.gitignore`, `LICENSE`, `README.md`,
`DOCUMENTATION.md`, `PROGRESS.md`, `CONVERSATION.md`, `novato/__init__.py`,
`novato/{detector,config,logger,intent_map,rules,safety}.py`,
`novato/backends/{__init__,basic_backend}.py`,
`tests/{test_detector,test_safety,test_intent,test_watcher,test_backends}.py`.
**Tests passing:** 66/66. **Lint:** clean.

### Prompt 2 — 2026-06-10 — Phase 2: Core Features
**What was built:** The full NLPM pipeline end to end — repository search across
four package managers + the AUR, relevance ranking, the rich terminal UI, a
safety-gated streaming executor, and the `main.py` CLI that wires it together
with slash-command routing and the `/mistake` hook entry point. Verified live on
this Arch machine with a real pacman + AUR search in dry-run mode.
**Files created:** `novato/{searcher,intent,ranker,presenter,executor,main}.py`,
`tests/{test_searcher,test_main}.py`.
**Bugs caught & fixed during live testing:** (1) wrong-PM correction emitted the
`install` subcommand as a package name; (2) confirm/choice prompts crashed with
`EOFError` when stderr was piped through stdin — prompts are now EOF-safe and the
hook reconnects stdin to `/dev/tty`. Both have regression tests.
**Tests passing:** 86/86. **Lint:** clean.

### Prompt 3 — 2026-06-10 — Phase 3: AI Backends
**What was built:** All three AI tiers behind one interface plus the router that
makes Novato unbreakable. Groq (online) and llamafile (offline) both resolve
intents and analyse errors, returning JSON the parser tolerates even with
markdown/prose noise; both enforce the safety layer on any fix they propose. The
router degrades gracefully (missing key / no binary / offline → Basic mode) and
the setup wizard onboards new users. All AI calls are dependency-injected so the
suite runs fully offline.
**Files created:** `novato/backends/{groq_backend,llamafile_backend,router}.py`,
`novato/setup_wizard.py`, `tests/{test_router,test_setup}.py`.
**Privacy:** Groq receives only the intent/error text the user typed — never
commands, paths, usernames, or distro details; returned package names are
validated against real local repos by the searcher.
**Tests passing:** 112/112. **Lint:** clean.

### Prompt 4 — 2026-06-10 — Phases 4 & 5: Slash Commands + Packaging (PROJECT COMPLETE)
**What was built:** The slash-command engines as dedicated modules and the real
shell integration that makes `/mistake` automatic. `watcher.py` installs an
idempotent, marker-guarded hook into `~/.zshrc` or `~/.bashrc` that pipes failed
commands to `novato --analyze-error` while staying invisible on success; it
removes cleanly and preserves the rest of the user's config. `teacher.py` powers
`/explain` with a PM + flag glossary; `switcher.py` powers `/switch` with a
validated menu. Packaging landed too: a `PKGBUILD` for the AUR and
`install.sh`/`uninstall.sh` (pipx/uv/pip, never sudo).
**Files created:** `novato/{watcher,teacher,switcher}.py`,
`tests/test_phase4.py`, `PKGBUILD`, `scripts/{install,uninstall}.sh`.
**Verified live on Arch:** `/switch` menu, `/mistake on` writes the hook,
`/mistake off` removes it leaving existing rc config intact.
**Tests passing:** 123/123. **Lint:** clean. **Build:** wheel + sdist OK.
