# Novato — User Manual

> **From novato to pro.** 🌱
> Your Linux terminal companion: install software by describing what you want,
> catch mistakes automatically, and learn Linux as you go.

This manual walks through **every feature**, step by step, with real commands and
expected output. If you just want the 60-second version, read
[Quick Start](#2-quick-start). Otherwise, work through it top to bottom.

---

## Table of contents

1. [Installing Novato](#1-installing-novato)
2. [Quick start (60 seconds)](#2-quick-start)
3. [Core concept: how Novato is used](#3-core-concept-how-novato-is-used)
4. [Feature 1 — Install by intent (NLPM)](#4-feature-1--install-by-intent-nlpm)
5. [Feature 2 — The silent error watcher (`/mistake`)](#5-feature-2--the-silent-error-watcher-mistake)
6. [Feature 3 — Teaching mode (`/explain`)](#6-feature-3--teaching-mode-explain)
6b. [Doing tasks & learning the terminal](#6b-doing-tasks--learning-the-terminal)
7. [AI modes and `/switch`](#7-ai-modes-and-switch)
8. [The setup wizard (`/setup`)](#8-the-setup-wizard-setup)
9. [Using the offline LLM (optional)](#9-using-the-offline-llm-optional)
10. [Using the online AI (Groq)](#10-using-the-online-ai-groq)
11. [Every command, in detail](#11-every-command-in-detail)
12. [Safety — what Novato will and won't do](#12-safety--what-novato-will-and-wont-do)
13. [Privacy — what is and isn't sent anywhere](#13-privacy--what-is-and-isnt-sent-anywhere)
14. [Files Novato creates](#14-files-novato-creates)
15. [Supported distributions](#15-supported-distributions)
16. [Troubleshooting](#16-troubleshooting)
17. [Uninstalling](#17-uninstalling)
18. [Quick reference card](#18-quick-reference-card)

---

## 1. Installing Novato

> ⚠️ **Note on the public install methods.** Options A, B, and D below require the
> GitHub repository to be **public**. A private repo returns `404` to anyone who
> isn't the owner, so the `curl` one-liner, the `pipx git+https://…` install, and
> the release tarball won't work until the repo is made public. The `yay -S
> novato` (AUR) method additionally requires the package to be **published to the
> AUR**. If you are the repository owner and just want to run Novato on your own
> machine, use **Option C (from source)** — it works regardless of visibility.

Pick **one** of these methods.

### Option A — One-line installer (easiest)

```bash
curl -fsSL https://raw.githubusercontent.com/Preethesh16/Novato/main/scripts/install.sh | bash
```

This uses `pipx` (or `uv`, or `pip --user`) and **never asks for sudo**.

### Option B — pipx (isolated, recommended)

```bash
pipx install git+https://github.com/Preethesh16/Novato.git
```

### Option C — From source (for development)

```bash
git clone https://github.com/Preethesh16/Novato
cd Novato
uv sync              # creates a virtualenv and installs everything
uv run novato --help # run it
```

### Option D — Arch Linux (AUR)

```bash
yay -S novato        # once the package is published to the AUR
```

### Verify it works

```bash
novato --version
novato /help
```

If `novato: command not found`, your user binary directory isn't on `PATH`. Add
`~/.local/bin` to your `PATH` and restart your terminal:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
source ~/.zshrc
```

---

## 2. Quick start

```bash
# 1. Install something by describing it (no setup needed — Basic mode is instant)
novato "i want to edit videos"

# 2. Turn on the silent error watcher (catches typos & mistakes automatically)
novato /mistake on
source ~/.zshrc          # or restart your terminal to activate the hook

# 3. Turn on teaching mode (explains every command it runs)
novato /explain on

# 4. (Optional) Enable smarter AI for tricky requests
novato /setup            # walks you through Groq / offline LLM
```

That's the whole tool. The rest of this manual explains each piece in depth.

---

## 3. Core concept: how Novato is used

Novato is a **command-line tool**, not a separate shell or app. You use it in
three shapes:

| You type… | Novato does… |
|---|---|
| `novato "plain english"` | Finds and installs software matching your description |
| `novato /command [arg]` | Runs a built-in command (settings, toggles, help) |
| *(nothing — runs in background)* | Watches for failed commands when `/mistake` is on |

**Two unbreakable rules to remember:**
- Novato **always shows you the exact command** before running it.
- Novato **always asks `y/N`** — nothing runs without your confirmation.

---

## 4. Feature 1 — Install by intent (NLPM)

This is the headline feature: **describe what you want, not the package name.**

### Step by step

**Step 1 — Run a query.** Wrap your request in quotes:

```bash
novato "i want to edit photos"
```

**Step 2 — Novato searches your real repositories.** It detects your distro,
picks the right package manager, and searches official repos (plus the AUR on
Arch). You'll see a status badge and a numbered list:

```text
[Novato • Basic ⚡] Searching repositories...

Found 4 option(s) for your system (Arch Linux):

  [1] gimp        — GNU Image Manipulation Program   (extra)
  [2] krita       — Digital painting studio          (extra)
  [3] darktable   — Photography workflow & raw editor (extra)
  [4] inkscape    — Vector graphics editor           (extra)
```

**Step 3 — Pick a number** (or `q` to quit):

```text
Pick [1-4] or 'q' to quit: 2
```

**Step 4 — Review the exact command.** Novato shows precisely what it will run:

```text
📋 Will run: sudo pacman -S krita
```

**Step 5 — Confirm.** Type `y` to proceed, or just press **Enter** for the safe
default (no):

```text
Confirm? [y/N]: y
```

**Step 6 — Watch it install.** Live output streams to your terminal, then:

```text
✅ Done! Try running 'krita'.
```

### Already-installed packages

Novato checks what's on your system before doing anything. Packages you already
have show a green **✓ installed** tag in the results list, and if you pick one,
Novato offers to **update it through the same source it came from** instead of
reinstalling:

```text
firefox is already installed (version 151.0.4-1, from the official repos).
Update it through the same source? [Y/n]:
```

An AUR package is updated with your AUR helper (`yay -S …`), an official one
with your package manager — so nothing ever drifts to the wrong source. Say `n`
and Novato leaves everything exactly as it is.

### Tips

- **Use natural words.** "a private browser", "something to record my screen",
  "terminal music player" all work. Filler words ("i want to", "please",
  "install") are ignored.
- **Typos are tolerated.** "edit vidio" still finds video editors.
- **AUR packages** (on Arch) are installed with your AUR helper (`yay`/`paru`) if
  you have one; otherwise they're shown but need a helper to install.
- **Preview without installing:** add `--dry-run` (see below).

### Dry-run mode

To see everything Novato *would* do without running a single command:

```bash
novato --dry-run "i want to edit videos"
```

It searches and shows the command, then stops — nothing is executed. Great for
learning what a request maps to.

---

## 5. Feature 2 — The silent error watcher (`/mistake`)

When enabled, Novato hooks into your shell and **only speaks when a command
fails**. It reads the error, explains it in plain English, and offers a fix.
While your commands succeed, it's completely invisible.

### Turning it on

```bash
novato /mistake on
```

You'll see:

```text
✅ mistake mode is now on.
Installed the /mistake hook in /home/you/.zshrc.
Run 'source ~/.zshrc' or restart your terminal to activate it.
```

**Activate it** by reloading your shell:

```bash
source ~/.zshrc          # zsh
# or
source ~/.bashrc         # bash
# or just open a new terminal
```

### What it looks like in action

Make a typo:

```text
$ sudo pacmna -S vlc
zsh: command not found: pacmna

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 Novato caught an error

  Error:   'pacmna' command not found
  Reason:  Looks like a typo — did you mean 'pacman'?
  Fix:     sudo pacman -S vlc

  Run: sudo pacman -S vlc [y/N]?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Press `y` to run the fix, or `Enter`/`n` to ignore it.

> **Cancelling is not a mistake.** If you stop a command yourself with
> **Ctrl+C** (or kill it), the watcher stays completely silent — it only reacts
> to commands that actually *failed*.

### Kinds of mistakes it catches

- **Typos** in commands (`pacmna` → `pacman`)
- **Wrong package manager** for your distro (`apt install …` on Arch → suggests
  `pacman`)
- **Missing `sudo`** when root is required
- **Missing Python modules** (`ModuleNotFoundError` → `pip install …`)
- **Missing Node modules** (`Cannot find module` → `npm install …`)
- **Package-manager locks** (stale `pacman` db lock), **keyring** problems
- **Disk full**, **port already in use**, **not a git repository**,
  **file not found**, **permission denied on a script** (needs `chmod +x`),
  **build tools missing**, and more.

### Turning it off

```bash
novato /mistake off
```

This **cleanly removes** the hook from your `~/.zshrc` / `~/.bashrc`, leaving the
rest of your config untouched.

> **Note:** The hook is wrapped in clearly-marked `# >>> novato … <<<` guards, so
> you can always see and remove it manually if you prefer.

---

## 6. Feature 3 — Teaching mode (`/explain`)

When teaching mode is on, every command Novato runs comes with a short,
plain-English explanation of what it does and what each flag means.

### Turning it on / off

```bash
novato /explain on
novato /explain off
novato /explain          # no argument = toggle current state
```

### What it looks like

With `/explain on`, an install shows an explanation block before the command:

```text
💡 Explain mode
   sudo    = run as administrator (needed for system changes)
   pacman  = Arch Linux's package manager (like an app store)
   -S      = Sync — download & install from the official servers
   vlc     = the exact package name being installed

📋 Will run: sudo pacman -S vlc
Confirm? [y/N]:
```

The explanation appears **after** the action is described and **never blocks**
it. It's designed to teach you the commands so that, over time, you don't need
Novato to run them for you — *from novato to pro.*

### Explaining *any* command

`/explain` also works on a command you give it directly — handy when you copy a
command from a forum or tutorial and want to know what it actually does before
running it:

```text
$ novato /explain ls -la /etc
💡 Explain mode
   ls   = list what's in a folder
   -la  = show all files, with full details
   /etc = the system configuration folder

$ novato /explain sudo rm -rf /tmp/cache
   sudo = run as administrator (needed for system changes)
   rm   = remove (delete) files — permanently, there's no undo
   -rf  = force-delete a folder and everything in it (very dangerous)
```

This is just an explanation — it never runs the command.

---

## 6b. Doing tasks & learning the terminal

Installing software is only part of being new to Linux. Novato also helps you
*do things* and *learn* — because a beginner knows the **task**, not the command.

### Describe a task, get the command

Just type what you want to do. Novato gives you the single simplest command and
offers to run it:

```text
$ novato "unzip messi file"
To unpack a .zip file:
   unzip messi.zip
Confirm? [y/N]:

$ novato "how do I rename a file"
To rename a file (it's the same 'move' command):
   mv oldname.txt newname.txt
   Replace the example name(s) above with your own, then run it.
```

If you'd rather be explicit, `/do "<task>"` does exactly the same thing, and
`/man "<task>"` shows the command **without** offering to run it:

```bash
novato /do "make a script runnable"
novato /man "extract a tar file"
```

Dangerous tasks (deleting files) are always shown with a warning and are *never*
run for you — Novato will not delete your data.

### `/learn` — the interactive tutorial

`novato /learn` walks you through the terminal **one command at a time**. Each
lesson explains an idea, lets you try it, and checks you got it before moving on.
Your progress is saved, so you can stop after any lesson and pick up later.

After the universal basics (navigation, files, permissions, finding things), it
unlocks a bonus track tailored to **your** distro — `apt`/snap/systemctl on
Ubuntu, `pacman`/AUR on Arch, `dnf`/SELinux on Fedora.

### `/cheat` — instant reference

Forgot a command? `novato /cheat <topic>` prints a quick table:

```bash
novato /cheat              # list the topics
novato /cheat files        # touch, mkdir, cp, mv, rm, cat...
novato /cheat shortcuts    # Tab, ↑, Ctrl+R, Ctrl+Shift+C/V...
novato /cheat network      # ping, curl, wget, ssh...
```

### `/disk` and `/process` — inspect your system

Two of the most common beginner panics have dedicated helpers:

```bash
novato /disk               # deep scan + optional safe cleanup + verify space
novato "why is my disk full"   # same thing, in plain English
novato "free storage for me"   # same smart cleanup flow
novato check space             # fast read-only available/used/total report
novato clean storage safely    # deep scan, confirm cleanup, verify again

novato /process            # what's running (and stop it, if you want)
novato /process 8080       # what's holding port 8080
novato "what's using port 8080"  # same thing, in plain English
```

`/process` lets you pick a program and stop it — always with a confirmation
first, never automatically.

---

## 7. AI modes and `/switch`

Novato has **four modes**. They control how it understands tricky requests. You
can change them anytime; **Basic mode always works** as the safety net.

| Mode | Engine | Speed | Internet? | Notes |
|---|---|---|---|---|
| **basic** | Rules + fuzzy matching | Instant | No | Default. 100% private. Always works. |
| **offline** | Local llamafile LLM | 3–8 s | No | Private. One-time model download. |
| **online** | Groq free API | ~0.2 s | Yes | Fastest. Free. Sends only your query text. |
| **both** ⭐ | Groq + llamafile fallback | Best | Either | Recommended. Online when possible, offline otherwise. |

### Checking and changing your mode

```bash
novato /switch              # show the menu and your current mode
novato /switch basic        # rules only, no AI
novato /switch offline      # local LLM only
novato /switch online       # Groq only
novato /switch both         # Groq + llamafile fallback (recommended)
```

Example of the menu:

```text
Current mode: basic

  basic    Rules only, no AI — instant, 100% private, always works.
  offline  Local llamafile LLM — private, works without internet.
  online   Groq API — fastest inference anywhere, completely free.
  both     Groq online + llamafile fallback — best experience.  ⭐

Use: /switch <mode>
```

### How the fallback chain works (mode `both`)

1. Try **Groq** (if you have a key and internet).
2. If that's unavailable, try the **offline LLM** (if a model is downloaded).
3. If that's unavailable too, fall back to **Basic mode**, which always answers.

This is why Novato can never fully break — there's always a working tier beneath.

---

## 8. The setup wizard (`/setup`)

The wizard runs automatically on first use, and you can re-run it anytime:

```bash
novato /setup
```

It walks you through:

1. **System detection** — shows your distro, package manager, and shell.
2. **Choosing an AI engine** — a menu with four choices:
   - `[1]` Offline LLM (llamafile) — *optional download*
   - `[2]` Online AI (Groq)
   - `[3]` Both ⭐ Recommended
   - `[s]` **Skip — stay on Basic mode** (no AI, always works)
3. **(If you chose offline/both)** It offers to download a local model. This is
   **opt-in**: the prompt defaults to **No**, so pressing Enter skips it.
4. **(If you chose online/both)** It opens the Groq console so you can paste a
   free API key.

> **You are never forced to download anything or sign up for anything.** Pick
> `[s]` and Novato works immediately in Basic mode. Everything else is optional.

---

## 9. Using the offline LLM (optional)

The offline tier runs a local model via a Mozilla **llamafile** — a single
self-contained file with no background service. **Nothing leaves your machine.**

### Do I need this if I have internet?

**No.** If you have internet + a Groq key, use `online` or `both` mode — Groq
is faster, smarter, and free. You do **not** need to download any model.

### So what is offline mode actually *for*?

Honest answer: **not for installing** — package downloads need the internet
anyway. Offline mode exists so Novato can still *think* (explain errors, teach,
diagnose) when the network can't be reached. Where it genuinely matters:

1. **The mistake-watcher — the killer case.** Think about *when* your internet
   is most likely broken: a bad Wi-Fi driver, a messed-up network config, DNS
   problems. That's exactly when you're typing failing commands and need help
   the most — and exactly when Groq is unreachable. The offline LLM can still
   read the error and explain *"your network service isn't running, try
   `systemctl start NetworkManager`"*. The moment you need a mentor most is the
   moment online AI is guaranteed to be unavailable.
2. **Error analysis & teaching in general.** Most of Novato isn't installing —
   it's explaining errors, teaching commands, diagnosing why something failed.
   None of that needs the internet, so the offline tier keeps the brain working
   everywhere: on a train, on a plane, behind a corporate firewall that blocks
   AI APIs.
3. **Privacy absolutists.** Some people will never send a single query to any
   API, period — even with internet available. For them offline isn't a
   fallback, it's the requirement: `novato /switch offline`.
4. **Groq simply being down** — outage, rate limit, region block. The fallback
   keeps the experience seamless.

In `both` mode, Novato tries Groq first and falls back to the local model
automatically — you never have to think about it manually.

---

### Which model should I pick?

The offline LLM comes in four sizes. **Bigger = smarter**, but needs more RAM
and is a larger one-time download. Here's what that means in practice:

| Your RAM | Model | Download | What it handles well |
|---|---|---|---|
| under 4 GB | TinyLlama 1.1B | ~600 MB | Simple, common requests ("video editor", "music player") |
| 4–8 GB | Phi-3-mini 3.8B | ~2.4 GB | Context + reasoning ("something lightweight to view PDFs") |
| 8–16 GB | Mistral-7B | ~4.1 GB | Nuanced requests, vague descriptions, edge cases |
| 16 GB+ | Llama-3.1-8B | ~4.7 GB | Best quality — handles anything you throw at it |

**The difference:** a smaller model knows what "video editor" means but may
struggle with "something to trim clips for youtube shorts without a watermark".
A bigger model understands the intent behind those creative descriptions.

**Recommendation:** If you have 4–8 GB RAM, Phi-3-mini is the sweet spot —
good reasoning, reasonable download size. If you only have 2–4 GB RAM,
TinyLlama still works for everyday requests (and Basic mode covers most of
those anyway, for free and instantly).

---

### Downloading a model

Auto-pick the right size for your RAM and enable offline mode:

```bash
novato --download-model
```

Or pick a specific model by name:

```bash
novato --download-model tinyllama-1.1b
novato --download-model phi3-mini
novato --download-model mistral-7b
novato --download-model llama3.1-8b
```

You'll see a live progress bar. The download is **resumable** — if it's
interrupted, running the command again picks up where it left off.

When it finishes, Novato saves the model path to your config and switches you
to `offline` mode (or `both` if you also have a Groq key).

### Already have a llamafile?

If you downloaded a llamafile yourself, point Novato at it by editing
`~/.novato/config.json` and setting:

```json
"llamafile_path": "/full/path/to/your-model.llamafile"
```

The offline tier activates automatically once a valid binary is set.

---

## 10. Using the online AI (Groq)

Groq is the fastest tier (~0.2 s) and **completely free** — no credit card, just
an email signup.

### Getting a key (step by step, ~1 minute)

1. Run `novato /setup` and choose `[2]` or `[3]` — Novato opens
   <https://console.groq.com/keys> in your browser and walks you through these
   same steps on screen. (You can also visit that address directly.)
2. **Sign up** with your email, Google, or GitHub. It's free — no credit card
   is ever asked.
3. Once logged in, click **"Create API Key"**.
4. Give it any name (e.g. `novato`) and click **Submit**.
5. A key starting with `gsk_...` is shown **once** — click **Copy**.
6. Come back to the terminal and **paste it** when Novato asks
   (right-click or `Ctrl+Shift+V` to paste in most terminals).

Novato verifies the key with a live test request and saves it to
`~/.novato/config.json` (readable only by you, file mode `600`). If you ever
lose the key, just create a new one the same way and re-run `novato /setup`.

### Switching to it

```bash
novato /switch online       # Groq only
novato /switch both         # Groq + offline fallback (recommended)
```

> **Privacy:** In online mode, Novato sends **only the text you type** (e.g.
> "edit videos") to Groq. It never sends your actual commands, file paths,
> usernames, or system details. See [Privacy](#13-privacy--what-is-and-isnt-sent-anywhere).

---

## 11. Every command, in detail

### Natural-language install

```bash
novato "what you want"
```
Searches your repos for software matching the description and installs your pick.

### `--dry-run`

```bash
novato --dry-run "what you want"
```
Does everything except execute — shows the command and stops. Safe for learning.

### `/help`

```bash
novato /help
```
Lists all commands with one-line descriptions.

### `/status`

```bash
novato /status
```
Shows your current settings:

```text
[Novato • Basic ⚡] current settings
  Mode:     basic
  Explain:  off
  Mistake:  off
  Distro:   Arch Linux
  PM:       pacman (+yay for AUR)
  Shell:    zsh
```

### `/switch [mode]`

```bash
novato /switch              # show menu + current mode
novato /switch both         # change mode
```
Modes: `basic`, `offline`, `online`, `both`.

### `/explain [on|off]`

```bash
novato /explain on
novato /explain off
novato /explain             # toggle
```
Turns the plain-English teaching explanations on or off.

### `/mistake [on|off]`

```bash
novato /mistake on          # installs the shell hook
novato /mistake off         # removes the shell hook
novato /mistake             # toggle
```
Enables/disables the silent error watcher. Remember to `source` your shell rc (or
open a new terminal) after turning it on.

### `/setup`

```bash
novato /setup
```
Re-runs the first-time onboarding wizard.

### `--download-model [MODEL]`

```bash
novato --download-model              # auto-select by RAM
novato --download-model phi3-mini    # specific model
```
Downloads an offline llamafile model and enables offline mode.

### `--version`

```bash
novato --version
```

### `--analyze-error` (internal)

```bash
novato --analyze-error "<command>" <exit_code>
```
You don't call this directly — the `/mistake` shell hook calls it for you. It's
documented here only so you understand what the hook does.

---

## 12. Safety — what Novato will and won't do

These rules are **absolute** and cannot be turned off:

✅ **Always:**
- Shows you the exact command before running it.
- Asks for `y/N` confirmation — the default is **No**.
- Logs every executed command to `~/.novato/history.log`.
- Strips dangerous auto-confirm flags (`--noconfirm`, `-y`, `--yes`) so you
  always get to review.
- Respects `--dry-run` (executes nothing).

🚫 **Never:**
- Auto-runs anything without your confirmation.
- Runs destructive commands — `rm`, `dd`, `mkfs`, `fdisk`, fork bombs, and
  similar are **refused outright**, even if an AI suggests them.
- Adds auto-confirm flags to install commands.

If Novato is ever unsure whether something is safe, it refuses and explains why.

---

## 13. Privacy — what is and isn't sent anywhere

| Mode | What leaves your machine |
|---|---|
| **Basic** | **Nothing.** Ever. |
| **Offline** | **Nothing.** The model runs locally. |
| **Online (Groq)** | **Only the intent text you type** (e.g. "edit videos"). |

In online mode, Novato **never** sends:
- your actual shell commands,
- file paths, usernames, or hostname,
- environment variables or system details,
- your command history.

The package names the AI suggests are checked against your **real local
repositories** before anything is shown, so a slightly-off suggestion is simply
filtered out. Your Groq API key is stored only in your local config file
(mode `600`, readable only by you).

---

## 14. Files Novato creates

Everything lives under `~/.novato/`:

| Path | Purpose |
|---|---|
| `~/.novato/config.json` | Your settings + Groq key (file mode `600`). |
| `~/.novato/history.log` | Append-only log of every executed command, timestamped. |
| `~/.novato/engine/` | Downloaded offline llamafile model(s). |

You can change the location by setting the `NOVATO_HOME` environment variable
(useful for portable installs or testing).

**Viewing your history:**

```bash
cat ~/.novato/history.log
```

Each line looks like:

```text
2026-06-11T14:03:21+05:30   EXEC      sudo pacman -S krita
2026-06-11T14:05:02+05:30   DRYRUN    sudo apt install vlc
2026-06-11T14:06:10+05:30   FIX       sudo pacman -S vlc
```

---

## 15. Supported distributions

Novato auto-detects your distro and uses the right package manager. Unknown
derivatives are handled via their `ID_LIKE` family, so most remixes work too.

| Family | Distros | Package manager | AUR |
|---|---|---|---|
| **Arch** | Arch, Manjaro, EndeavourOS, Garuda, Artix | `pacman` (+ `yay`/`paru`) | ✅ |
| **Debian** | Debian, Ubuntu, Mint, Pop!_OS, elementary, Zorin, Kali, Raspberry Pi OS | `apt` | — |
| **Fedora** | Fedora, RHEL, Rocky, AlmaLinux, CentOS | `dnf` | — |
| **openSUSE** | Leap, Tumbleweed, SLES | `zypper` | — |

If your distro isn't recognized, Basic-mode commands are limited, but Novato
won't break — it tells you clearly.

---

## 16. Troubleshooting

**`novato: command not found`**
Your user bin directory isn't on `PATH`. Add `~/.local/bin` to `PATH` and restart
your shell (see [Installing](#1-installing-novato)).

**The `/mistake` watcher isn't catching errors.**
Did you reload your shell after enabling it? Run `source ~/.zshrc` (or
`~/.bashrc`), or open a new terminal. Check it's installed with `novato /status`.

**"I couldn't map that to packages."**
Try simpler words ("video editor" instead of a long sentence), or enable an AI
mode: `novato /switch both` (after `/setup`).

**No search results.**
You may be offline, or the package name differs on your distro. On Debian/Ubuntu,
run `sudo apt update` first to refresh the package list.

**A model download was interrupted.**
Just run `novato --download-model` again — it resumes automatically.

**Online mode isn't working.**
Check your key and internet with `novato /status`. Novato automatically falls
back to offline/basic if Groq is unreachable, so you're never stuck.

**I want to remove the shell hook manually.**
Open `~/.zshrc` / `~/.bashrc` and delete the block between
`# >>> novato mistake hook >>>` and `# <<< novato mistake hook <<<`.

**Updating to the latest version.**
Don't use `pipx install --force` — on systems where pipx uses **uv** as its
backend, `--force` fails with *"A virtual environment already exists … Use
`--clear`"* and silently leaves the **old version** installed. Do a clean
uninstall + install instead:

```bash
pipx uninstall novato
pipx install git+https://github.com/Preethesh16/Novato.git
```

Your settings in `~/.novato/` (Groq key, mode, watcher) are kept — only the
program itself is replaced, so the setup wizard won't re-run.

---

## 17. Uninstalling

The bundled uninstaller removes the package, the shell hook, and (optionally)
your config and history:

```bash
curl -fsSL https://raw.githubusercontent.com/Preethesh16/Novato/main/scripts/uninstall.sh | bash
```

Or manually:

```bash
pipx uninstall novato        # or: pip uninstall novato
novato /mistake off          # remove the shell hook (run before uninstalling)
rm -rf ~/.novato             # remove config, history, and downloaded models
```

---

## 18. Quick reference card

```text
INSTALL BY INTENT
  novato "i want to edit videos"      find & install matching software
  novato --dry-run "..."              preview without running anything

TEACHING & ERROR-CATCHING
  novato /explain on|off              plain-English explanations
  novato /mistake on|off              silent error watcher (shell hook)
        (run 'source ~/.zshrc' after turning /mistake on)

AI MODES
  novato /switch                      show modes + current
  novato /switch basic|offline|online|both
  novato --download-model [MODEL]     get the offline local LLM (optional)

INFO & SETUP
  novato /status                      current settings
  novato /setup                       re-run onboarding wizard
  novato /help                        list all commands
  novato --version                    show version

SAFETY: every command is shown and confirmed (default = No). Destructive
        commands (rm, dd, mkfs, …) are always refused.
PRIVACY: Basic & Offline send nothing; Online sends only your query text.
FILES:  ~/.novato/{config.json, history.log, engine/}
```

---

*Novato is free and open source (GPLv3). Contributions — new intents, error rules,
and distro support — are welcome. See [DOCUMENTATION.md](DOCUMENTATION.md) for the
technical reference and how to extend it.*

**From novato to pro.** 🌱
