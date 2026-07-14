# Novato 🌱

> **From novato to pro.**
> A Linux terminal companion that lets you install software by describing what
> you want, quietly catches your mistakes, and teaches you Linux as you go.

Novato (*"beginner"* in Spanish & Portuguese) makes the terminal human — without
dumbing down the power Linux gives you.

```text
$ novato "i want to edit videos"

[Novato • Basic ⚡] Searching repositories...

Found 4 options for your system (Arch Linux):

  [1] kdenlive   — Powerful non-linear video editor by KDE   (official repo)
  [2] shotcut    — Free, cross-platform video editor          (official repo)
  [3] openshot   — Beginner-friendly video editor             (AUR)
  [4] davinci-resolve — Professional editor by Blackmagic      (AUR)

Pick [1-4] or 'q' to quit: 2

📋 Will run: sudo pacman -S shotcut
Confirm? [y/N]: y
✅ Installing shotcut...
```

---

## What it does

Novato is a full terminal companion for newcomers:

1. **Install by intent** — type what you *want* ("a private browser"), not the
   exact package name. Novato detects your distro, searches the right
   repositories, and shows you the exact command before running anything.
2. **Do tasks in plain English** — *"unzip this file"*, *"rename a file"*,
   *"why is my disk full"*. Novato gives you the one simple command for the job
   and offers to run it. A beginner knows the *task*, not the command name —
   so describe the task.
3. **Catch mistakes** — an opt-in, *silent* watcher only speaks when a command
   fails. It explains the error in plain English and offers a fix.
4. **Learn, the easy way** — a step-by-step `/learn` tutorial (one command at a
   time, with a check that it landed), instant `/cheat` references, and
   `/explain ls -la` to break down *any* command flag by flag.

### Beyond installing — describe the task

```text
$ novato "unzip messi file"

To unpack a .zip file:
   unzip messi.zip
Confirm? [y/N]:

$ novato "why is my disk full"
💾 Disk space + the biggest folders eating your space...

$ novato /explain chmod 755 script.sh
💡 chmod = change permissions · 755 = owner can do everything, others can read/run
```

You don't have to remember command names — but Novato teaches them as you go, so
one day you won't need it. That's the point.

---

## Install

The recommended way is to install straight from GitHub as a **global `novato`
command** — no PyPI account, no `uv run` prefix. Use a CLI installer
(`pipx` or `uv`) so it lands in its own isolated environment and on your `PATH`:

```bash
# Option A — pipx (most distros)
pipx install git+https://github.com/Preethesh16/Novato.git
pipx ensurepath          # one-time: makes `novato` available in new shells

# Option B — uv
uv tool install git+https://github.com/Preethesh16/Novato.git
uv tool update-shell     # one-time PATH setup

# Then, from anywhere:
novato --help
```

> Don't have an installer yet? `python -m pip install --user pipx` (or grab `uv`
> from <https://astral.sh/uv>). On Arch/Manjaro you can also `sudo pacman -S
> python-pipx`. Plain `pip install --user` fails on modern Linux because the
> system Python is externally managed — that's what `pipx`/`uv` exist to solve.

```bash
# Update later, or remove:
pipx upgrade novato       # (uv: uv tool upgrade novato)
pipx uninstall novato     # (uv: uv tool uninstall novato)
```

**From source (for hacking on Novato):**

```bash
git clone https://github.com/Preethesh16/Novato.git
cd Novato
uv sync                   # create env + install deps
uv run novato --help
uv run pytest             # run the test suite
```

```bash
# Coming soon, once published:
pip install novato        # PyPI
yay -S novato             # Arch User Repository
```

First run launches a one-time setup wizard. You can skip it and stay on **Basic
mode**, which works instantly with zero internet and zero AI. To enable the
fully-offline local LLM at any time:

```bash
novato --download-model     # auto-picks a model for your RAM, then enables offline mode
```

---

## Quick start — all three features

```bash
# 1. Install by intent
novato "i want to edit photos"

# 2. Teaching mode
novato /explain on
novato "install vlc"

# 3. Silent error watcher (hooks into your shell)
novato /mistake on
sudo pacmna -S vlc        # typo → Novato catches it and suggests the fix
```

---

## Slash commands

| Command | What it does |
|---|---|
| `/do "<task>"` | Do a terminal task by describing it (e.g. `/do "rename a file"`) |
| `/man "<task>"` | Show the one command for a task — no execution, just the answer |
| `/learn` | Interactive, step-by-step terminal tutorial (distro-aware) |
| `/cheat [topic]` | Quick command reference (`files`, `network`, `shortcuts`, …) |
| `/explain <command>` | Explain any command flag by flag (e.g. `/explain ls -la /etc`) |
| `/explain [on\|off]` | Toggle teaching mode on installs |
| `/disk` | Deep-scan storage, offer safe distro-aware cleanup, then verify free space |
| `/space` | Quickly show total, used, and available storage (read-only) |
| `/clean storage` | Run the safe deep-scan and cleanup workflow |
| `/process [port]` | See what's running, or what's using a port — and stop it |
| `/switch [online\|offline\|both\|basic]` | Change AI mode (no arg shows a menu) |
| `/mistake [on\|off]` | Toggle the silent error watcher |
| `/status` | Show current mode, toggles, distro, and shell |
| `/setup` | Re-run the first-time setup wizard |
| `/help` | Show all commands |

> **Tip:** anything `/do` and `/man` can do, you can also just *type* — `novato
> "unzip this file"` works the same. `/disk` and `/process` are named shortcuts
> for `novato "why is my disk full"` and `novato "what's using port 8080"`. The
> slash forms are there for when you want to be explicit.

### Smart storage cleanup

Use `novato check space` for an immediate read-only capacity report. Use
`novato clean storage safely`, ask `novato "free storage for me"`, or run
`novato /disk` for cleanup. Novato detects the package manager used by Arch,
Ubuntu/Debian, or Fedora, then:

1. performs a read-only deep scan and shows current free space, large folders,
   and the biggest application-cache areas;
2. identifies measurable cleanup such as downloaded package files, Trash, and
   oversized old system logs;
3. explains and shows every cleanup command, asking `y/N` separately for each;
4. scans again and reports the actual space recovered and space remaining.

On Arch, Novato uses `paccache`'s read-only preview when available, so it only
quotes package archives that can really be pruned instead of the entire pacman
cache. A detected `yay` build directory is explained and offered separately via
`yay -Sc --aur`. Recovery is measured on both `/` and `/home`, which may be
different filesystems.

Personal files and arbitrary application-cache folders are review-only. Novato
does not guess that Downloads, projects, photos, or offline app data are junk.

The deep scan is distro-independent: it walks the home filesystem without
following symlinks or crossing mounts, inspects modification age and file type,
recognises source repositories and configuration as important, aggregates
generated trees such as `node_modules`, virtual environments, Gradle caches,
and compiler output, and content-hashes same-sized large files before reporting
them as duplicates. It also inventories the root filesystem separately and
protects system-managed areas. File paths and hashes never leave the machine.

After the report, Novato offers an interactive drill-down menu. Pick any
candidate to see its next folder level, measured size, newest-content age,
classification evidence, and exact proposed action. Generated project folders
and old files are moved to Trash first; Android platforms, build-tools, system
images, and virtual devices are handled with `sdkmanager`/`avdmanager`. Nothing
is selected automatically, and every action has its own default-No confirmation.

Storage routing uses Novato's intent system rather than a substring shortcut.
Online and Offline modes ask their language model to classify the user's goal;
Basic mode falls back to private concept, synonym, and typo-aware matching. This
keeps paraphrases working while preventing requests such as "clean this code"
or "install a disk usage tool" from launching storage cleanup.

---

## Supported distros

| Family | Distros | Package manager | AUR |
|---|---|---|---|
| Arch | Arch, Manjaro, EndeavourOS, Garuda, Artix | `pacman` (+ `yay`/`paru`) | ✅ |
| Debian | Debian, Ubuntu, Mint, Pop!_OS, elementary, Zorin, Kali | `apt` | — |
| Fedora | Fedora, RHEL, Rocky, AlmaLinux, CentOS | `dnf` | — |
| openSUSE | Leap, Tumbleweed, SLES | `zypper` | — |

Unknown derivatives are auto-detected via `ID_LIKE`, so most remixes work too.

---

## AI modes

| Mode | Engine | Speed | Privacy | Needs |
|---|---|---|---|---|
| **Basic** ⚡ | Rules + fuzzy match | instant | 100% local | nothing (always works) |
| **Offline** 🔒 | llamafile (local LLM) | 3–8 s | 100% local | one-time model download |
| **Online** ⚡ | Groq free API | ~200 ms | query only* | free email signup |
| **Both** ⭐ | Groq + llamafile fallback | best | best effort | both of the above |

\* Novato never sends your actual commands, file paths, usernames, or system
info to any online service — only the intent you type. See the
[privacy policy](DOCUMENTATION.md#privacy).

### Do I need the offline model if I have internet?

**No.** If you have internet + a Groq key, the online tier handles everything
and is faster. The router handles fallback automatically in `both` mode — Groq
runs first; the local model only kicks in when Groq is unreachable.

### What is offline mode actually *for*, then?

Fair question — installing packages needs the internet anyway (the download
comes from your distro's mirrors). Offline mode isn't for installing. It's so
Novato can still **think** — explain errors, teach, diagnose — when the network
can't be reached:

1. **The mistake-watcher — the killer case.** When is your internet most likely
   broken? Bad Wi-Fi driver, messed-up network config, DNS problems. That's
   exactly when you're typing failing commands and need help the most — and
   exactly when any online AI is guaranteed to be unreachable. The offline LLM
   can still read the error and explain *"your network service isn't running,
   try `systemctl start NetworkManager`"*. The moment you need a mentor most is
   the moment online AI cannot help.
2. **Error analysis & teaching in general.** Most of Novato isn't installing —
   it's explaining errors, teaching commands, diagnosing failures. None of that
   needs the internet, so the offline tier keeps the brain working everywhere:
   on a train, on a plane, behind a corporate firewall that blocks AI APIs.
3. **Privacy absolutists.** Some people will never send a single query to any
   API, period — even with internet available. For them offline isn't a
   fallback, it's the requirement (`/switch offline`).
4. **Groq simply being down** — outage, rate limit, region block. The router
   falls through to the local model automatically, so the experience stays
   seamless.

### Offline model tiers (which model should I pick?)

The offline LLM comes in four sizes. Bigger = smarter answers, but needs more
RAM and is a larger one-time download.

| RAM | Auto-selected model | Download size | Good at |
|---|---|---|---|
| under 4 GB | TinyLlama 1.1B | ~600 MB | Simple, common requests |
| 4–8 GB | Phi-3-mini 3.8B | ~2.4 GB | Good reasoning, understands context |
| 8–16 GB | Mistral-7B | ~4.1 GB | Strong general knowledge, nuanced queries |
| 16 GB+ | Llama-3.1-8B | ~4.7 GB | Best quality, handles vague/complex requests |

`novato --download-model` auto-picks based on your available RAM. The smarter
the model, the better it handles unusual or creative descriptions — e.g.
"something lightweight to read PDFs without all the bloat" vs. just "pdf viewer".
For most users, **Phi-3-mini** (4–8 GB RAM) is the sweet spot.

---

## Safety

Novato has **absolute, non-negotiable** safety rules:

- It **never** auto-runs anything — every command is shown and confirmed.
- It **never** emits auto-confirm flags (`--noconfirm`, `-y`, `--yes`).
- It **never** runs system-bricking commands (`dd`, `mkfs`, `fdisk`, fork bombs,
  `rm -rf /`, wildcard or system-path deletes …) — these are shown for reference
  only and refused outright.
- **Deleting a file you named** (`novato "delete report.txt"`) *is* offered, but
  only ever for **one specific, in-tree file/folder**, behind a loud warning and
  a default-**No** confirmation. Anything broader (`rm *`, `rm ~`, absolute or
  system paths, `rm -rf`) stays blocked.
- It logs every executed command to `~/.novato/history.log`.

See [DOCUMENTATION.md](DOCUMENTATION.md) for the full architecture and rules.

---

## Full documentation

- **[USERMANUAL.md](USERMANUAL.md)** — step-by-step guide to every feature.
- **[DOCUMENTATION.md](DOCUMENTATION.md)** — architecture and technical reference.
- **[CHANGELOG.md](CHANGELOG.md)** — every fix and change, with the reasoning behind it.

## Contributing

Contributions are very welcome — especially new intents, error rules, and distro
support. See [DOCUMENTATION.md](DOCUMENTATION.md) for how to add each. Run the
test suite with:

```bash
uv run pytest
```

---

## License

**GPLv3** (GNU General Public License v3.0 or later) — see [LICENSE](LICENSE).
Copyleft keeps Novato and every fork free and open, which fits a tool meant to
live inside Linux distributions. Every dependency is open source.
