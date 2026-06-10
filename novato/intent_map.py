# SPDX-License-Identifier: GPL-3.0-or-later
"""Static intent -> package candidates map (Basic mode).

This is the heart of Novato's zero-dependency Basic mode. It maps plain-English
intents to ordered lists of candidate package names. The first entries are the
most beginner-friendly / popular choices.

Design notes
------------
* Package names use the *Arch* naming convention as the canonical form because
  Arch + AUR has the widest coverage. The searcher/ranker layer is responsible
  for translating to apt/dnf/zypper equivalents where they differ. Entries that
  only exist via the AUR (``-bin`` suffixes, etc.) are still useful hints.
* Keys are short, lowercased intent phrases. Lookup is fuzzy (see
  ``basic_backend``) so "edit videos" still matches "edit video".
* Keep this list curated and ordered by friendliness — it is user-facing.

To add a new intent: add a key and an ordered list of packages. Run
``pytest tests/test_intent.py`` to confirm the structure stays valid.
"""

from __future__ import annotations

# Grouped for human maintainability; flattened into INTENT_MAP at the bottom.
_MULTIMEDIA = {
    "edit video": ["kdenlive", "shotcut", "openshot", "davinci-resolve"],
    "video editor": ["kdenlive", "shotcut", "openshot", "davinci-resolve"],
    "watch video": ["vlc", "mpv", "celluloid"],
    "video player": ["vlc", "mpv", "celluloid", "smplayer"],
    "play movies": ["vlc", "mpv", "celluloid"],
    "edit photo": ["gimp", "darktable", "krita", "inkscape"],
    "photo editor": ["gimp", "krita", "darktable"],
    "draw": ["krita", "gimp", "inkscape", "mypaint"],
    "vector graphics": ["inkscape"],
    "3d modeling": ["blender", "freecad"],
    "cad": ["freecad", "librecad", "openscad"],
    "view photo": ["eog", "feh", "geeqie", "gwenview"],
    "image viewer": ["eog", "feh", "gwenview", "nomacs"],
    "music": ["rhythmbox", "clementine", "strawberry", "lollypop"],
    "music player": ["rhythmbox", "strawberry", "clementine"],
    "terminal music": ["cmus", "ncmpcpp", "moc", "mpd"],
    "spotify": ["spotify", "spotify-launcher", "ncspot"],
    "podcast": ["gpodder", "kasts"],
    "audio editor": ["audacity", "ardour", "tenacity"],
    "make music": ["lmms", "ardour", "audacity"],
    "dj": ["mixxx"],
    "record screen": ["obs-studio", "simplescreenrecorder", "kooha"],
    "screen recorder": ["obs-studio", "simplescreenrecorder", "kooha"],
    "stream": ["obs-studio"],
    "screenshot": ["flameshot", "gnome-screenshot", "spectacle", "scrot"],
    "media server": ["jellyfin", "plex-media-server", "kodi"],
    "convert video": ["handbrake", "ffmpeg"],
    "convert audio": ["soundconverter", "ffmpeg"],
    "rip dvd": ["handbrake", "dvdrip"],
}

_INTERNET = {
    "browser": ["firefox", "chromium", "brave-bin", "vivaldi"],
    "web browser": ["firefox", "chromium", "brave-bin"],
    "private browser": ["librewolf", "tor-browser", "brave-bin"],
    "lightweight browser": ["falkon", "midori", "qutebrowser", "surf"],
    "terminal browser": ["lynx", "w3m", "links"],
    "torrent": ["qbittorrent", "transmission-gtk", "deluge", "fragments"],
    "terminal torrent": ["transmission-cli", "rtorrent", "aria2"],
    "download manager": ["aria2", "uget", "wget", "curl"],
    "vpn": ["openvpn", "wireguard-tools", "mullvad-vpn", "protonvpn"],
    "email": ["thunderbird", "evolution", "geary", "mailspring"],
    "terminal email": ["neomutt", "mutt", "aerc"],
    "rss reader": ["newsboat", "liferea", "fluent-reader"],
    "ftp": ["filezilla", "lftp"],
    "irc": ["weechat", "irssi", "hexchat"],
    "remote desktop": ["remmina", "rustdesk-bin", "tigervnc"],
    "ssh": ["openssh"],
    "ssh client": ["openssh", "mosh"],
    "network monitor": ["nethogs", "bmon", "iftop", "vnstat"],
    "network scanner": ["nmap", "arp-scan"],
    "wifi": ["networkmanager", "iwd", "wavemon"],
    "wireshark": ["wireshark-qt"],
    "packet capture": ["wireshark-qt", "tcpdump", "termshark"],
}

_PRODUCTIVITY = {
    "office": ["libreoffice-fresh", "onlyoffice-bin", "wps-office"],
    "office suite": ["libreoffice-fresh", "onlyoffice-bin"],
    "word processor": ["libreoffice-writer", "abiword"],
    "spreadsheet": ["libreoffice-calc", "gnumeric"],
    "presentation": ["libreoffice-impress"],
    "pdf": ["evince", "okular", "zathura", "mupdf"],
    "pdf reader": ["evince", "okular", "zathura"],
    "edit pdf": ["xournalpp", "pdfarranger", "libreoffice-draw"],
    "note taking": ["obsidian", "joplin-desktop", "notable", "logseq-desktop-bin"],
    "notes": ["obsidian", "joplin-desktop", "standard-notes-bin"],
    "terminal notes": ["nb", "jrnl"],
    "markdown editor": ["marktext-bin", "ghostwriter", "apostrophe"],
    "calendar": ["gnome-calendar", "korganizer", "calcurse"],
    "todo": ["taskwarrior", "todoman"],
    "mind map": ["freeplane", "xmind"],
    "diagram": ["drawio-desktop", "dia"],
    "ebook": ["calibre", "foliate"],
    "ebook reader": ["foliate", "calibre", "koreader"],
    "dictionary": ["goldendict", "artha"],
    "scan": ["simple-scan", "skanlite", "xsane"],
    "ocr": ["tesseract", "gimagereader"],
    "password": ["keepassxc", "bitwarden-bin", "pass"],
    "password manager": ["keepassxc", "bitwarden-bin", "pass"],
    "two factor": ["authenticator", "keepassxc"],
}

_COMMUNICATION = {
    "chat": ["discord", "telegram-desktop", "signal-desktop", "element-desktop"],
    "discord": ["discord", "vesktop-bin"],
    "telegram": ["telegram-desktop"],
    "signal": ["signal-desktop"],
    "slack": ["slack-desktop"],
    "matrix": ["element-desktop", "fractal"],
    "video call": ["zoom", "teams-for-linux", "jitsi-meet-desktop"],
    "zoom": ["zoom"],
    "social media": ["ferdium-bin", "rambox-bin"],
    "whatsapp": ["whatsapp-for-linux", "whatsdesk-bin"],
}

_DEVELOPMENT = {
    "code editor": ["neovim", "vscodium-bin", "code", "sublime-text-4"],
    "text editor": ["gedit", "kate", "mousepad", "geany"],
    "ide": ["jetbrains-toolbox", "code", "eclipse-java"],
    "vim": ["neovim", "vim", "gvim"],
    "emacs": ["emacs"],
    "python ide": ["pycharm-community-edition", "code", "thonny"],
    "git": ["git"],
    "git gui": ["gitg", "git-cola", "lazygit", "gitkraken"],
    "docker": ["docker", "docker-compose", "docker-buildx"],
    "podman": ["podman", "podman-compose"],
    "kubernetes": ["kubectl", "k9s", "minikube", "helm"],
    "database": ["dbeaver", "mysql-workbench", "pgadmin4"],
    "sql client": ["dbeaver", "sqlitebrowser"],
    "postgres": ["postgresql", "pgadmin4"],
    "mysql": ["mariadb", "mysql-workbench"],
    "redis": ["redis"],
    "mongodb": ["mongodb-bin", "mongodb-compass"],
    "api test": ["insomnia", "postman-bin", "httpie", "hoppscotch-desktop"],
    "rest client": ["insomnia", "httpie", "postman-bin"],
    "compiler": ["gcc", "clang"],
    "build tools": ["base-devel", "cmake", "make"],
    "node": ["nodejs", "npm"],
    "java": ["jdk-openjdk", "jre-openjdk"],
    "rust": ["rustup", "rust"],
    "go": ["go"],
    "virtual machine": ["virtualbox", "virt-manager", "gnome-boxes"],
    "terminal multiplexer": ["tmux", "zellij", "screen"],
    "terminal emulator": ["kitty", "alacritty", "wezterm", "foot"],
    "regex": ["regexploit"],
    "json": ["jq", "fx"],
    "http server": ["caddy", "nginx", "lighttpd"],
}

_SYSTEM = {
    "system monitor": ["htop", "btop", "gnome-system-monitor"],
    "task manager": ["htop", "btop", "gnome-system-monitor"],
    "process monitor": ["htop", "btop", "glances"],
    "disk usage": ["ncdu", "baobab", "qdirstat", "dust"],
    "partition": ["gparted", "gnome-disk-utility"],
    "file manager": ["nautilus", "dolphin", "thunar", "nemo"],
    "terminal file manager": ["lf", "yazi", "ranger", "nnn"],
    "backup": ["timeshift", "deja-dup", "borg", "restic"],
    "sync files": ["syncthing", "rclone", "rsync"],
    "cloud storage": ["rclone", "nextcloud-client", "megasync"],
    "firewall": ["ufw", "firewalld", "gufw"],
    "antivirus": ["clamav", "clamtk"],
    "compress": ["p7zip", "unzip", "ark", "file-roller"],
    "archive manager": ["ark", "file-roller", "xarchiver"],
    "clipboard": ["copyq", "clipman"],
    "launcher": ["rofi", "wofi", "ulauncher"],
    "system info": ["fastfetch", "neofetch", "inxi"],
    "benchmark": ["sysbench", "stress", "geekbench"],
    "temperature": ["lm_sensors", "psensor"],
    "battery": ["tlp", "powertop", "auto-cpufreq"],
    "bootloader": ["grub", "refind"],
    "package cleanup": ["pacman-contrib", "bleachbit"],
    "boot usb": ["balena-etcher", "ventoy", "popsicle"],
    "burn iso": ["balena-etcher", "brasero", "k3b"],
    "format usb": ["gnome-disk-utility", "gparted"],
}

_GAMING = {
    "gaming": ["steam", "lutris", "heroic-games-launcher-bin"],
    "steam": ["steam"],
    "game launcher": ["lutris", "heroic-games-launcher-bin", "bottles"],
    "windows games": ["wine", "bottles", "lutris"],
    "emulator": ["retroarch", "dolphin-emu", "pcsx2"],
    "minecraft": ["prismlauncher", "minecraft-launcher"],
    "discord overlay": ["discord"],
    "controller": ["antimicrox", "sc-controller"],
    "game performance": ["gamemode", "mangohud"],
}

_CREATIVE = {
    "music production": ["ardour", "lmms", "reaper"],
    "video conversion": ["handbrake", "ffmpeg"],
    "color picker": ["gpick", "gcolor3"],
    "font manager": ["font-manager"],
    "icon editor": ["gimp", "inkscape"],
    "animation": ["blender", "synfigstudio", "opentoonz"],
    "comic": ["krita", "mcomix"],
    "screencast gif": ["peek", "kooha"],
}

_LEARNING = {
    "typing": ["gtypist", "klavaro", "typespeed"],
    "flashcards": ["anki"],
    "math": ["geogebra", "octave", "maxima"],
    "statistics": ["r", "jamovi", "pspp"],
    "astronomy": ["stellarium", "kstars"],
    "chemistry": ["avogadro", "kalzium"],
    "programming practice": ["code", "thonny"],
    "language learning": ["anki"],
}

_UTILITIES = {
    "calculator": ["gnome-calculator", "qalculate-gtk", "speedcrunch"],
    "weather": ["gnome-weather", "wttrbar"],
    "color scheme": ["pywal", "wpgtk"],
    "wallpaper": ["nitrogen", "feh", "variety"],
    "theme": ["lxappearance", "qt5ct"],
    "screen brightness": ["brightnessctl", "redshift", "gammastep"],
    "night light": ["redshift", "gammastep"],
    "bluetooth": ["bluez", "blueman", "bluez-utils"],
    "audio control": ["pavucontrol", "pulsemixer", "easyeffects"],
    "screen lock": ["i3lock", "swaylock", "betterlockscreen"],
    "notification": ["dunst", "mako"],
    "status bar": ["polybar", "waybar", "i3status"],
    "window manager": ["i3-wm", "hyprland", "sway", "bspwm"],
    "compositor": ["picom"],
    "magnifier": ["magnus"],
    "qr code": ["qrencode", "zbar"],
    "macro": ["xdotool", "ydotool"],
    "keyboard remap": ["keyd", "xremap"],
}

_FINANCE_AND_MISC = {
    "budget": ["gnucash", "homebank", "kmymoney"],
    "accounting": ["gnucash", "kmymoney"],
    "invoice": ["invoiceninja", "gnucash"],
    "crypto wallet": ["electrum", "monero-gui"],
    "stocks": ["gnucash"],
    "recipe": ["gourmand"],
    "family tree": ["gramps"],
    "genealogy": ["gramps"],
    "translate": ["dialect", "crow-translate"],
    "subtitle": ["subtitleeditor", "gnome-subtitles"],
    "karaoke": ["performous", "ultrastardx"],
    "guitar": ["tuxguitar"],
    "sheet music": ["musescore", "lilypond"],
    "metronome": ["gtick"],
    "tuner": ["gtuner"],
}

_PRIVACY_SECURITY = {
    "encrypt": ["veracrypt", "gnupg", "cryptsetup"],
    "encrypt files": ["veracrypt", "gocryptfs", "cryptomator"],
    "gpg": ["gnupg"],
    "shred files": ["coreutils"],
    "metadata removal": ["mat2", "exiftool"],
    "tor": ["tor", "tor-browser"],
    "pentest": ["nmap", "metasploit", "aircrack-ng"],
    "vulnerability scan": ["nmap", "nikto", "openvas"],
    "firewall gui": ["gufw", "firewall-config"],
    "secrets scan": ["gitleaks", "trufflehog"],
    "yubikey": ["yubikey-manager", "yubico-authenticator-bin"],
    "fingerprint": ["fprintd"],
}

_VIRTUALIZATION_CLOUD = {
    "aws cli": ["aws-cli"],
    "terraform": ["terraform", "opentofu"],
    "ansible": ["ansible"],
    "vagrant": ["vagrant"],
    "cloud sync": ["rclone"],
    "s3 client": ["s3cmd", "rclone"],
    "container gui": ["podman-desktop", "lazydocker"],
    "vm manager": ["virt-manager", "gnome-boxes", "virtualbox"],
    "windows vm": ["virt-manager", "virtualbox"],
}

_WRITING_BLOGGING = {
    "latex": ["texlive-core", "texstudio", "texmaker"],
    "blog": ["hugo", "zola", "jekyll"],
    "static site": ["hugo", "zola", "jekyll"],
    "grammar": ["languagetool"],
    "writing": ["ghostwriter", "focuswriter", "libreoffice-writer"],
    "distraction free writing": ["focuswriter", "ghostwriter"],
    "bibliography": ["zotero", "jabref"],
    "citations": ["zotero", "jabref"],
}

# Flatten all category dicts into one. Later groups override earlier ones on
# key collision (none expected — keep keys unique).
INTENT_MAP: dict[str, list[str]] = {}
for _group in (
    _MULTIMEDIA,
    _INTERNET,
    _PRODUCTIVITY,
    _COMMUNICATION,
    _DEVELOPMENT,
    _SYSTEM,
    _GAMING,
    _CREATIVE,
    _LEARNING,
    _UTILITIES,
    _FINANCE_AND_MISC,
    _PRIVACY_SECURITY,
    _VIRTUALIZATION_CLOUD,
    _WRITING_BLOGGING,
):
    INTENT_MAP.update(_group)


# Short human-readable descriptions for popular packages. Used by the presenter
# when a live repo description is unavailable (e.g. offline Basic mode).
PACKAGE_DESCRIPTIONS: dict[str, str] = {
    "vlc": "Versatile multimedia player that plays almost any format",
    "mpv": "Minimal, scriptable, keyboard-driven media player",
    "kdenlive": "Powerful non-linear video editor by KDE",
    "shotcut": "Free, cross-platform video editor",
    "openshot": "Beginner-friendly video editor",
    "gimp": "Full-featured raster image editor",
    "krita": "Digital painting studio loved by artists",
    "inkscape": "Professional vector graphics editor",
    "firefox": "Fast, private, open-source web browser",
    "chromium": "Open-source base of Google Chrome",
    "librewolf": "Privacy-hardened fork of Firefox",
    "qbittorrent": "Open-source BitTorrent client, no ads",
    "keepassxc": "Offline, encrypted password manager",
    "obsidian": "Markdown knowledge base with backlinks",
    "libreoffice-fresh": "Complete open-source office suite",
    "thunderbird": "Full-featured desktop email client",
    "discord": "Voice, video, and text chat for communities",
    "telegram-desktop": "Fast, cloud-based messaging app",
    "neovim": "Hyperextensible, modern Vim-based editor",
    "code": "Visual Studio Code — popular extensible editor",
    "vscodium-bin": "Telemetry-free build of VS Code",
    "docker": "Container engine for building and running apps",
    "htop": "Interactive process viewer for the terminal",
    "btop": "Beautiful resource monitor for the terminal",
    "ncdu": "Disk-usage analyser with an ncurses interface",
    "timeshift": "System restore tool using snapshots",
    "steam": "Valve's PC gaming platform and store",
    "obs-studio": "Studio-grade screen recording and streaming",
    "flameshot": "Powerful yet simple screenshot tool",
    "kitty": "Fast, GPU-accelerated terminal emulator",
    "alacritty": "GPU-accelerated, minimalist terminal emulator",
}


def lookup(intent: str) -> list[str]:
    """Return candidate packages for an exact (normalised) intent key.

    Returns an empty list if the intent is not in the map. Fuzzy lookup lives
    in :mod:`novato.backends.basic_backend`.
    """
    return list(INTENT_MAP.get(intent.strip().lower(), []))


def all_intents() -> list[str]:
    """Return every intent key (sorted) — handy for ``--list-intents``."""
    return sorted(INTENT_MAP)


def describe(package: str) -> str:
    """Return a short human description for a package, or empty string."""
    return PACKAGE_DESCRIPTIONS.get(package, "")
