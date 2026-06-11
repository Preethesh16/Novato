# Changelog

All notable fixes and changes to Novato are documented here, newest first.
This complements the git history with the *why* behind each change.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/),
and the project aims to follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

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
