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

```bash
# From PyPI (recommended for most users)
pip install novato

# On Arch / Manjaro (AUR)
yay -S novato            # once published

# From source (development)
git clone https://github.com/novato-cli/novato
cd novato
uv sync                  # create env + install deps
uv run novato --help
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
| `/disk` | See what's filling up your disk (free space + biggest folders) |
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
- It **never** suggests destructive commands (`rm`, `dd`, `mkfs`, …) and refuses
  to run them.
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
