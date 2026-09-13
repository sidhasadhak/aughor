#!/bin/sh
# Aughor installer for macOS and Linux.
#
#   ./install.sh               install everything Aughor needs, start it, open it in a browser
#   ./install.sh --no-start    install only
#   ./install.sh --help        every option
#
# Or without cloning first (Aughor is downloaded into ./aughor):
#   curl -LsSf https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.sh | sh
#
# Run it again whenever you like: it only redoes what changed.
#
# This script does just the two things a shell has to: find the checkout and get uv. It then
# hands over to `python -m aughor.installer`, which runs the same steps on every OS
# (install.ps1 is this file's Windows twin). Kept ASCII so no locale can garble it.
set -eu

# AUGHOR_REPO_URL installs from a fork (or a local clone) instead.
REPO_URL="${AUGHOR_REPO_URL:-https://github.com/sidhasadhak/aughor.git}"
PYTHON_VERSION="3.11"  # aughor/installer.py PYTHON_VERSION

bold="" red="" green="" reset=""
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
  bold=$(printf '\033[1m') red=$(printf '\033[31m') green=$(printf '\033[32m') reset=$(printf '\033[0m')
fi
tick="+" cross="x"
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
  *UTF-8* | *utf-8* | *UTF8* | *utf8*) tick=$(printf '\342\234\223') cross=$(printf '\342\234\227') ;;
esac

ok() { printf '  %s%s%s %s\n' "$green" "$tick" "$reset" "$1"; }
fail() {
  printf '\n  %s%s %s%s\n' "$red" "$cross" "$1" "$reset" >&2
  [ -n "${2:-}" ] && printf '  %s\n' "$2" >&2
  printf '\n' >&2
  exit 1
}

printf '\n  %sAughor installer%s\n\n' "$bold" "$reset"

# ── Find the checkout (or download one) ──────────────────────────────────────────
is_checkout() {
  [ -f "$1/pyproject.toml" ] && [ -f "$1/web/package.json" ] &&
    grep -q '^name = "aughor"' "$1/pyproject.toml"
}

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || script_dir=""
if [ -n "$script_dir" ] && is_checkout "$script_dir"; then
  ROOT=$script_dir
elif is_checkout "$(pwd -P)"; then
  ROOT=$(pwd -P)
else
  ROOT=${AUGHOR_DIR:-$(pwd -P)/aughor}
  if ! is_checkout "$ROOT"; then
    command -v git >/dev/null 2>&1 ||
      fail "Git is needed to download Aughor." "Install Git (https://git-scm.com/downloads), then run this again."
    printf '  Downloading Aughor into %s...\n' "$ROOT"
    git clone --quiet "$REPO_URL" "$ROOT" ||
      fail "Could not download Aughor." "Check your internet connection, then run this again."
    ok "Aughor downloaded"
  fi
fi

LOGS="$ROOT/.aughor/logs"
mkdir -p "$LOGS"

# ── Get uv, the one tool the rest cannot install through itself ───────────────────
find_uv() {
  for candidate in "$(command -v uv 2>/dev/null || true)" "${XDG_BIN_HOME:+$XDG_BIN_HOME/uv}" \
    "$HOME/.local/bin/uv" "${CARGO_HOME:-$HOME/.cargo}/bin/uv"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! UV=$(find_uv); then
  printf '  Installing uv, the Python package manager Aughor uses...\n'
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh 2>>"$LOGS/uv-install.log" | sh >>"$LOGS/uv-install.log" 2>&1 || true
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh 2>>"$LOGS/uv-install.log" | sh >>"$LOGS/uv-install.log" 2>&1 || true
  else
    fail "Could not install uv: this computer has neither curl nor wget." \
      "Install uv (https://docs.astral.sh/uv/), then run this again."
  fi
  UV=$(find_uv) ||
    fail "Could not install uv." "Check your internet connection, then run this again. Log: $LOGS/uv-install.log"
  ok "uv installed"
  export AUGHOR_UV_INSTALLED=1
fi

uv_version=$("$UV" --version 2>/dev/null || true)
uv_version=${uv_version#uv }
uv_version=${uv_version%% *}
case "$uv_version" in
  0.[0-7] | 0.[0-7].*)
    fail "uv $uv_version is too old for Aughor." "Update it (uv self update, or your package manager), then run this again."
    ;;
esac

cd "$ROOT"
if ! "$UV" python find "$PYTHON_VERSION" >/dev/null 2>&1; then
  printf '  Installing Python %s...\n' "$PYTHON_VERSION"
  "$UV" python install "$PYTHON_VERSION" >"$LOGS/python-install.log" 2>&1 ||
    fail "Could not install Python $PYTHON_VERSION." "Check your internet connection, then run this again. Log: $LOGS/python-install.log"
  ok "Python $PYTHON_VERSION installed"
fi

# ── Hand over: every remaining step is the same on every OS ───────────────────────
# --isolated --no-project: a throwaway environment, never the project's .venv, which the
# first step may have to rebuild.
export AUGHOR_BOOTSTRAP=1
exec "$UV" run --quiet --no-project --isolated --python "$PYTHON_VERSION" python -m aughor.installer "$@"
