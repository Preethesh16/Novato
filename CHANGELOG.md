# Changelog

All notable fixes and changes to Novato are documented here, newest first.
This complements the git history with the *why* behind each change.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/),
and the project aims to follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### New features — a companion for absolute beginners

A new-to-Linux user has to climb a much taller wall than "which package do I
install": navigating folders, copying and deleting files, reading errors,
freeing disk space. This release widens Novato from an installer into a full
terminal companion, while keeping the core promise: one tool, plain English,
always works offline.

#### Describe a task, get the command (`novato.howto`, `/do`, `/man`)
- **Why:** Beginners know the *task* ("unzip this file"), not the command
  (`tar`/`unzip`). Asking them to look up a man page assumes the very knowledge
  they lack.
- **What:** A curated task→command knowledge base (`novato/howto.py`, ~180
  phrasings) answers "how do I ..." with **one** simple command and a one-line
  explanation. It's integrated into the normal `novato "..."` flow (a high match
  threshold keeps genuine package requests untouched), with explicit `/do
  "<task>"` (offers to run it) and `/man "<task>"` (shows it only) entry points.
  Argument extraction fills in the user's own filename when given (`unzip messi
  file` → `unzip messi.zip`); multi-argument and destructive tasks are shown for
  reference and never auto-run.

#### Interactive, distro-aware tutorial (`/learn`)
- **Why:** The fastest way to *stop* needing a crutch is to learn — one step at
  a time, with feedback.
- **What:** `novato/learner.py` teaches one command per lesson (explain → try →
  check), saves progress between runs, and after the universal basics unlocks a
  track tailored to the user's distro (Ubuntu/Debian, Arch, or Fedora). Lessons
  only ever execute vetted read-only commands; deleting is taught as a concept,
  never run.

#### Instant cheat-sheets (`/cheat`)
- **What:** `novato/cheat.py` prints a clean, plain-English reference table per
  topic (`files`, `network`, `shortcuts`, …) — fully offline, no AI.

#### Explain any command, not just installs (`/explain <command>`)
- **Why:** People paste commands from forums without knowing what they do.
- **What:** `/explain ls -la /etc` now breaks down an arbitrary command flag by
  flag, with a glossary of ~40 everyday commands, their common flags, and
  well-known paths (`teacher.explain_arbitrary_command`). `/explain on|off`
  still toggles teaching mode.

#### Disk and process helpers (`/disk`, `/process`)
- **Why:** "My disk is full" and "something's using a port" have no GUI to fall
  back on for a terminal newcomer.
- **What:** `novato/sysinfo.py` powers `/disk` (free space + biggest folders,
  suggests `ncdu`) and `/process [port]` (what's running / holding a port, with
  a confirmed, never-automatic stop). Both are also reachable in plain English
  ("why is my disk full", "what's using port 8080").

#### One-time "things nobody tells you" tips in setup
- **What:** Setup now ends with a one-time panel covering the survival
  shortcuts — copy/paste is `Ctrl+Shift+C/V` (not `Ctrl+C`, which kills the
  command!), Tab completion, `↑` history, `Ctrl+R`, `Ctrl+C`, `Ctrl+L`. Tracked
  by `config.tips_shown` so re-running `/setup` doesn't nag.

#### Argument parsing handles dashes in commands/queries
- **Fix:** `main()` now peels leading global flags off itself, so a command like
  `/explain ls -la` or `find . -name x` no longer makes argparse choke on the
  embedded `-la`/`-name`.

### Reliability fixes

#### Online mode no longer silently dies behind a blocked DNS port
- **Problem:** The connectivity check probed `1.1.1.1:53` (DNS). Many
  networks/firewalls block outbound port 53 to external servers even when HTTPS
  works fine, so Novato wrongly concluded "offline", dropped the Groq tier, and
  fell back to Basic — the badge still said "Groq" but queries failed to map.
- **Fix:** The probe now targets `api.groq.com:443` (the host the online tier
  actually needs), with a Cloudflare `:443` fallback. This is what made
  `install firefox` intermittently report "I couldn't map that to packages".

#### Literal package names always work, even offline in Basic mode
- **Problem:** Typing a real package name like `firefox` failed when no AI tier
  was available, because Basic mode only maps *intents* ("web browser"), not
  package names.
- **Fix:** When intent mapping yields nothing, Novato now does a direct repo
  search on the meaningful words of the query (stopwords like "install"
  stripped, but no singularisation so names like `nodejs` survive). Real
  package names resolve every time, with zero AI.

#### Installed packages are detected; updates go through the original source
- **Problem:** Picking a package that was already on the system triggered a
  blind reinstall. Worse, an AUR package "updated" via plain pacman wouldn't
  actually rebuild from the AUR.
- **Fix:** New `novato/installed.py` queries what's installed (one fast call:
  `pacman -Q` / `dpkg-query -W` / `rpm -qa`) and, on Arch, which packages are
  foreign (`pacman -Qm` = AUR). Search results now show a green `✓ installed`
  tag, and choosing an installed package offers an update **through the same
  source it came from**: `yay -S` for AUR packages, `pacman -S` for official,
  `apt install --only-upgrade`, `dnf upgrade`, `zypper update` elsewhere.
  Declining leaves the system untouched.

#### Specific apps with non-obvious package names now resolve (e.g. Brave)
- **Problem:** Asking for Brave returned only generic browsers. The AI suggests
  the app name ("brave" / "brave-browser"), but the Arch package is
  `brave-bin` — and candidate resolution only kept exact name matches, so the
  suggestion was silently dropped.
- **Fix:** Candidate resolution now picks the most plausible package: exact
  name → name with a known packaging suffix (`-bin`, `-git`, …) → most popular
  name-prefix match. Hyphenated candidates that find nothing are retried on
  their first word (`brave-browser` → `brave` → finds `brave-bin`).

### Newbie-safety & UX fixes

These changes came out of real first-run testing on Arch Linux, where a
beginner hit several rough edges. Each one is meant to make Novato "do it for
the user" instead of assuming Linux knowledge.

#### Cancelling a command (Ctrl+C) is no longer treated as a mistake
- **Problem:** Pressing Ctrl+C makes the shell report exit code 130
  (128 + SIGINT). The mistake-watcher only checked "exit ≠ 0", so deliberately
  stopping a command triggered Novato's error-analysis panel — "I cancelled it
  myself, why is Novato correcting me?"
- **Fix,** at three layers:
  - The shell hook now skips signal exits (`exit_code < 128` guard), so no
    `novato` process is even spawned on Ctrl+C / kill.
  - `novato --analyze-error` itself returns silently for exit codes ≥ 128 —
    this protects machines that still have the *old* hook text in their rc
    file, because the hook is baked in at install time.
  - `install_hook()` now **upgrades outdated hook blocks in place** (instead of
    saying "already installed"), so running `/mistake on` once after updating
    refreshes the hook to the latest version.
- Also: Ctrl+C during a Novato-run install no longer prints a Python traceback
  or a scary "✖ Install exited with code 130" — the executor catches the
  interrupt and Novato says "Cancelled — nothing was changed." A top-level
  guard in `main()` makes Ctrl+C anywhere (menus, downloads, prompts) exit
  quietly with the conventional code 130.

#### Enable the mistake-watcher during setup (no manual activation)
- **Problem:** `novato /mistake on` writes a hook to `~/.zshrc`, but a *child
  process can never reload its parent shell* — so the watcher didn't start
  until the user manually ran `source ~/.zshrc` or opened a new terminal. A
  beginner has no way to know that.
- **Fix:** The first-run setup wizard now offers to enable the mistake-watcher
  (recommended, default Yes). The hook is written during onboarding, so every
  new terminal the user opens already has it — zero manual steps.
- The shell hook now exports `NOVATO_MISTAKE_ACTIVE=1`. When a user runs
  `/mistake on` in a shell that *already* has the hook live, Novato detects it
  and says "already active" instead of nagging about activation.
- When activation genuinely is needed, the message is plain-English:
  "Just close this terminal and open a new one" (the `source` command is
  offered only as a parenthetical for those who want it).

#### Partial-upgrade guard (the "install firefox → 404 everywhere" bug)
- **Problem:** On Arch (rolling release), `pacman -S firefox` against a stale
  package database fails with a 404 on every mirror, because the version in the
  local list has already been removed from the servers. A beginner cannot
  diagnose this.
- **Fix:** Before every install, Novato now offers to refresh first (default
  Yes) with a plain-English explanation of the trap. Distro-aware:
  `sudo pacman -Syu` on Arch, `sudo apt update` on Debian/Ubuntu; dnf/zypper
  auto-refresh so no prompt is shown.
- Added `SystemInfo.sync_cmd` and a per-distro `sync` entry in the detector.
- Added `Presenter.ask_yes_no()` for free-form yes/no prompts with a choosable
  default.

#### Interactive package-manager prompts are now visible
- **Problem:** Novato captured install output line-by-line through a pipe, so
  pacman's `:: Proceed with installation? [Y/n]` prompt (which has no trailing
  newline) never flushed to the screen — the install appeared to hang.
- **Fix:** Install commands now inherit the terminal's stdin/stdout/stderr
  directly (`subprocess.run` with an inherited TTY), so the package manager's
  own prompts appear and accept input normally.

#### Search results no longer wrap awkwardly
- **Problem:** Long package descriptions pushed the `(extra)` / `(AUR)` repo
  tag onto a new line, breaking the clean numbered list.
- **Fix:** Descriptions are truncated to fit the terminal width and the line is
  rendered with `no_wrap`, keeping each result on a single tidy line.

### Onboarding

#### Auto-trigger the setup wizard on first run
- **Problem:** After installing, running `novato` jumped straight to a query —
  the setup wizard (mode selection, Groq key, etc.) was only reachable via
  `/setup`, so users never saw it.
- **Fix:** `main()` now checks `config.setup_complete` and launches the wizard
  automatically on first run, then rebuilds the app so the chosen mode/keys are
  active in the same session.

#### Full feature overview after setup
- The wizard's closing screen now prints a complete, plain-text reference of
  every feature (install-by-intent, teaching mode, mistake-watcher, switch
  modes, download model, status) so users know exactly what they can do.

#### Choose which offline model to download
- **Problem:** The wizard silently auto-picked one offline model.
- **Fix:** It now lists all four models (TinyLlama / Phi-3-mini / Mistral-7B /
  Llama-3.1-8B) with size, RAM requirement, and a one-line capability note, and
  marks the one recommended for the user's RAM. The user picks, or skips.

### Documentation
- Documented the offline-model tiers (RAM, size, capability) and clarified that
  **the offline LLM is unnecessary if you have internet + a Groq key** — online
  is faster and the local model is only a fallback for offline/privacy. Added to
  both `README.md` and `USERMANUAL.md`.
- Added "What is offline mode actually for?" to README and USERMANUAL: offline
  isn't for installing (package downloads need internet anyway) — it's so the
  mistake-watcher and teaching can still think when the network itself is the
  problem, behind firewalls, for privacy absolutists, or during Groq outages.
  All four fallback chains verified working (`both`+offline → llamafile→basic;
  `both`+online → groq→llamafile→basic; `offline` → never probes the network;
  `online`+net-down → basic rules).

---

## [0.1.0] — initial release

- **Phases 1–3:** distro detection, config, logging, the curated intent map,
  the rules engine, the safety layer, and the three AI backend tiers
  (Basic → llamafile offline → Groq online) behind a fallback router.
- **Phases 4–5:** slash commands (`/status`, `/help`, `/switch`, `/explain`,
  `/mistake`, `/setup`), the shell mistake-watcher hook, and packaging
  (`pyproject.toml`, install/uninstall scripts, PKGBUILD).
- **Automatic llamafile download:** resumable, atomic, RAM-aware model fetch so
  the offline tier is turnkey rather than a manual step.
- **Offline LLM made strictly optional** in setup — Basic mode always works
  with zero downloads and zero signups.
- **Relicensed from MIT to GPLv3** (copyleft fits a Linux system tool that
  lives alongside pacman/apt/coreutils).
- Added `USERMANUAL.md` and `DOCUMENTATION.md`.
