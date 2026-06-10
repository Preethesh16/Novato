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

Novato does three things at once:

1. **Install by intent** — type what you *want* ("a private browser"), not the
   exact package name. Novato detects your distro, searches the right
   repositories, and shows you the exact command before running anything.
2. **Catch mistakes** — an opt-in, *silent* watcher only speaks when a command
   fails. It explains the error in plain English and offers a fix.
3. **Teach as you go** — turn on `/explain` and every action comes with a short,
   respectful explanation of what each command and flag does.

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
| `/switch [online\|offline\|both\|basic]` | Change AI mode (no arg shows a menu) |
| `/explain [on\|off]` | Toggle teaching mode |
| `/mistake [on\|off]` | Toggle the silent error watcher |
| `/status` | Show current mode, toggles, distro, and shell |
| `/setup` | Re-run the first-time setup wizard |
| `/help` | Show all commands |
| `/update` | Update Novato to the latest version |

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
| **Offline** 🔒 | llamafile (local LLM) | 3–8 s | 100% local | ~1.5 GB one-time download |
| **Online** ⚡ | Groq free API | ~200 ms | query only* | free email signup |
| **Both** ⭐ | Groq + llamafile fallback | best | best effort | both of the above |

\* Novato never sends your actual commands, file paths, usernames, or system
info to any online service — only the intent you type. See the
[privacy policy](DOCUMENTATION.md#privacy).

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
