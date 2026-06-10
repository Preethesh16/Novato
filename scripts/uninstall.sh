#!/usr/bin/env bash
# Novato uninstaller. Removes the package, the shell hook, and (optionally) your
# config + history. Never uses sudo.
set -euo pipefail

GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
info() { printf '%s\n' "${GREEN}==>${RESET} $*"; }
warn() { printf '%s\n' "${YELLOW}warning:${RESET} $*" >&2; }

NOVATO_HOME="${NOVATO_HOME:-$HOME/.novato}"
BEGIN_MARKER="# >>> novato mistake hook >>>"
END_MARKER="# <<< novato mistake hook <<<"

# 1. Remove the shell hook from rc files (idempotent, preserves other config).
remove_hook() {
    local rc="$1"
    [ -f "$rc" ] || return 0
    if grep -qF "$BEGIN_MARKER" "$rc"; then
        info "Removing /mistake hook from $rc"
        # Delete the marked block.
        sed -i.novato-bak "/$(printf '%s' "$BEGIN_MARKER" | sed 's/[][\.*^$/]/\\&/g')/,/$(printf '%s' "$END_MARKER" | sed 's/[][\.*^$/]/\\&/g')/d" "$rc"
        rm -f "$rc.novato-bak"
    fi
}
remove_hook "$HOME/.zshrc"
remove_hook "$HOME/.bashrc"

# 2. Uninstall the package (try each installer we might have used).
if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q novato; then
    info "Uninstalling via pipx..."
    pipx uninstall novato || true
elif command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q novato; then
    info "Uninstalling via uv tool..."
    uv tool uninstall novato || true
else
    info "Uninstalling via pip..."
    python3 -m pip uninstall -y novato || true
fi

# 3. Offer to remove config + history.
if [ -d "$NOVATO_HOME" ]; then
    printf '%s' "Remove your Novato config & history at ${NOVATO_HOME}? [y/N]: "
    read -r answer || answer="n"
    case "$answer" in
        y|Y|yes) rm -rf "$NOVATO_HOME"; info "Removed ${NOVATO_HOME}." ;;
        *) info "Kept ${NOVATO_HOME}. ${DIM}(delete it manually anytime)${RESET}" ;;
    esac
fi

echo
info "Novato uninstalled. Thanks for trying it — come back anytime. 🌱"
