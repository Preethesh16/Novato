#!/usr/bin/env bash
# Novato one-line installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Preethesh16/Novato/main/scripts/install.sh | bash
#
# Prefers pipx (isolated, recommended), falls back to pip --user. Never uses
# sudo: Novato is a user tool and only asks for root when it installs a package
# you confirmed.
set -euo pipefail

REPO="${NOVATO_REPO:-https://github.com/Preethesh16/Novato}"
GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; DIM=$'\033[2m'; RESET=$'\033[0m'

info()  { printf '%s\n' "${GREEN}==>${RESET} $*"; }
warn()  { printf '%s\n' "${YELLOW}warning:${RESET} $*" >&2; }
die()   { printf '%s\n' "${RED}error:${RESET} $*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required but not found."

# Check Python is >= 3.10.
python3 - <<'PY' || die "Novato needs Python 3.10 or newer."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

install_with_pipx() {
    info "Installing Novato with pipx..."
    pipx install "git+${REPO}.git" --force
}

install_with_pip() {
    info "Installing Novato with pip (--user)..."
    python3 -m pip install --user --upgrade "git+${REPO}.git"
}

if command -v pipx >/dev/null 2>&1; then
    install_with_pipx
elif command -v uv >/dev/null 2>&1; then
    info "Installing Novato with uv tool..."
    uv tool install "git+${REPO}.git"
else
    warn "pipx/uv not found; using pip --user. (pipx is recommended.)"
    install_with_pip
fi

echo
if command -v novato >/dev/null 2>&1; then
    info "Novato installed! ${DIM}$(command -v novato)${RESET}"
else
    warn "Installed, but 'novato' isn't on your PATH yet."
    warn "Add your user bin to PATH (e.g. ~/.local/bin) and restart your shell."
fi

cat <<EOF

  ${GREEN}From novato to pro.${RESET} 🌱

  Get started:
    novato "i want to edit videos"
    novato /setup            ${DIM}# enable AI modes (optional)${RESET}
    novato /mistake on       ${DIM}# catch errors automatically${RESET}
    novato /help

EOF
