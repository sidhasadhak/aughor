#!/bin/sh
# Aughor installer for macOS and Linux.
#
# On a computer without Aughor, one line does everything: downloads Aughor into ~/aughor,
# installs what it needs, starts it and opens it in the browser. Nothing has to be installed
# first, not even Git:
#   curl -LsSf https://raw.githubusercontent.com/sidhasadhak/aughor/main/install.sh | sh
#
# Inside a checkout:
#   ./install.sh               install everything Aughor needs, start it, open it in a browser
#   ./install.sh --no-start    install only
#   ./install.sh --help        every option
#
# Run it again whenever you like: it only redoes what changed.
#
# This script does just what a shell has to: find the checkout (or download one) and get uv.
# It then hands over to `python -m aughor.installer`, which runs the same steps on every OS
# (install.ps1 is this file's Windows twin). Kept ASCII so no locale can garble it.
#
# Everything runs inside main(), called on the very last line: through `curl | sh`, `sh` runs
# a script as it arrives, and a download cut off halfway must define functions and run nothing.
set -eu

main() {
  # AUGHOR_REPO_URL and AUGHOR_ARCHIVE_URL install from a fork (or a local copy) instead.
  REPO_URL="${AUGHOR_REPO_URL:-https://github.com/sidhasadhak/aughor.git}"
  ARCHIVE_URL="${AUGHOR_ARCHIVE_URL:-https://github.com/sidhasadhak/aughor/archive/refs/heads/main.tar.gz}"
  PYTHON_VERSION="3.11" # aughor/installer.py PYTHON_VERSION

  setup_output
  printf '\n  %sAughor installer%s\n\n' "$bold" "$reset"
  blank=1 # the header ends with a blank line

  # Before the first slow step, not after three retries into it.
  preflight github.com
  find_checkout
  # The hint for next time has to name the checkout when this terminal is not in it.
  if [ "$ROOT" != "$(pwd -P)" ]; then
    export AUGHOR_CHECKOUT_DIR="$ROOT"
  fi
  LOGS="$ROOT/.aughor/logs"
  mkdir -p "$LOGS"

  preflight astral.sh
  ensure_uv
  check_uv_version
  cd "$ROOT"
  ensure_python

  # Hand over: every remaining step is the same on every OS. --isolated --no-project: a
  # throwaway environment, never the project's .venv, which the first step may rebuild.
  export AUGHOR_BOOTSTRAP=1
  exec "$UV" run --quiet --no-project --isolated --python "$PYTHON_VERSION" python -m aughor.installer "$@"
}

setup_output() {
  bold="" red="" green="" reset="" blank=""
  if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
    bold=$(printf '\033[1m') red=$(printf '\033[31m') green=$(printf '\033[32m') reset=$(printf '\033[0m')
  fi
  tick="+" cross="x"
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8* | *utf-8* | *UTF8* | *utf8*) tick=$(printf '\342\234\223') cross=$(printf '\342\234\227') ;;
  esac
}

say() {
  printf '  %s\n' "$1"
  blank=""
}

ok() {
  printf '  %s%s%s %s\n' "$green" "$tick" "$reset" "$1"
  blank=""
}

fail() {
  [ -n "${blank:-}" ] || printf '\n' >&2 # one blank line before a failure, never two
  printf '  %s%s %s%s\n' "$red" "$cross" "$1" "$reset" >&2
  [ -n "${2:-}" ] && printf '  %s\n' "$2" >&2
  printf '\n' >&2
  exit 1
}

is_checkout() {
  [ -f "$1/pyproject.toml" ] && [ -f "$1/web/package.json" ] &&
    grep -q '^name = "aughor"' "$1/pyproject.toml"
}

# The folder this script sits in, the current folder, or — when neither is a checkout, as under
# `curl | sh` — a fresh download into ~/aughor (or AUGHOR_DIR), wherever the terminal happens to be.
find_checkout() {
  script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || script_dir=""
  if [ -n "$script_dir" ] && is_checkout "$script_dir"; then
    ROOT=$script_dir
  elif is_checkout "$(pwd -P)"; then
    ROOT=$(pwd -P)
  else
    ROOT=${AUGHOR_DIR:-$HOME/aughor}
    if ! is_checkout "$ROOT"; then
      # Never write into a folder that holds anything else: a failed download is cleaned up
      # with `rm -rf`, and that must only ever meet what the download itself put there.
      if [ -e "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
        fail "$ROOT already exists, and it isn't Aughor." \
          "Move it out of the way, or pick another folder with AUGHOR_DIR=/some/folder, then run this again."
      fi
      say "Downloading Aughor into $ROOT..."
      DOWNLOAD_LOG="${TMPDIR:-/tmp}"
      DOWNLOAD_LOG="${DOWNLOAD_LOG%/}/aughor-download.log" # macOS's TMPDIR ends in a slash
      : >"$DOWNLOAD_LOG"
      download_aughor "$ROOT" ||
        {
          proxy_hint_if_certificate "$DOWNLOAD_LOG"
          fail "Could not download Aughor." "Check your internet connection, then run this again. Log: $DOWNLOAD_LOG"
        }
      ok "Aughor downloaded"
    fi
    ROOT=$(CDPATH='' cd -- "$ROOT" && pwd -P)
  fi
}

# A clone when this computer has a working Git, so the checkout can `git pull` later;
# otherwise the same code as a snapshot, so a fresh computer needs nothing installed first.
download_aughor() {
  if have_git; then
    if git clone --quiet "$REPO_URL" "$1" >>"$DOWNLOAD_LOG" 2>&1 </dev/null; then
      return 0
    fi
    # IN-3 — a throttled or flaky GitHub fails a full clone long before it fails a blobless
    # one, which fetches far less to reach the same working tree. Tried once, then the
    # snapshot path below, so a hostile network degrades rather than stops.
    rm -rf "$1"
    echo "full clone failed; trying a blobless clone" >>"$DOWNLOAD_LOG"
    if git clone --quiet --filter=blob:none "$REPO_URL" "$1" >>"$DOWNLOAD_LOG" 2>&1 </dev/null; then
      return 0
    fi
  fi
  rm -rf "$1" # a failed clone's leftovers: find_checkout refused a folder with anything else in it
  mkdir -p "$(dirname "$1")" || return 1
  staging=$(mktemp -d "$(dirname "$1")/.aughor-download.XXXXXX") || return 1
  if fetch "$ARCHIVE_URL" "$staging/aughor.tar.gz" &&
    tar -xzf "$staging/aughor.tar.gz" -C "$staging" 2>>"$DOWNLOAD_LOG"; then
    for unpacked in "$staging"/*/; do
      if [ -f "${unpacked}pyproject.toml" ]; then
        mv "${unpacked%/}" "$1" && rm -rf "$staging" && return 0
      fi
    done
    echo "the downloaded archive holds no Aughor checkout" >>"$DOWNLOAD_LOG"
  fi
  rm -rf "$staging"
  return 1
}

# A Mac without the Command Line Tools has a /usr/bin/git that only opens Apple's installer
# dialog, so it counts as no Git.
have_git() {
  command -v git >/dev/null 2>&1 || return 1
  if [ "$(uname -s)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
    return 1
  fi
  git --version >/dev/null 2>&1
}

# IN-3 — a preflight, so an unreachable network is named in a second rather than discovered
# three retries into the first slow step. It probes ONLY reachability of the host the very
# next step needs, with a short timeout, and it never blocks: a probe that cannot run (no
# curl, a host that refuses HEAD) must not stop an install that would have worked. A warning
# is the whole contribution — it turns "it hung for two minutes then failed" into "this host
# is unreachable" before the waiting starts.
preflight() {
  command -v curl >/dev/null 2>&1 || return 0
  for host in "$@"; do
    if ! curl -sSf --connect-timeout 5 --max-time 8 -o /dev/null "https://$host" 2>/dev/null; then
      say ""
      say "Warning: $host did not answer. The next step downloads from it."
      say "If this is a corporate network, a proxy or its certificate is the usual reason."
      return 0
    fi
  done
}

# IN-3 — one attempt is not an answer on a hostile network. Three tries, doubling from a
# second. POSIX sh throughout: no arrays, no `local`, no bashisms.
fetch() {
  fetch_try=1
  fetch_wait=1
  while :; do
    if fetch_once "$1" "$2"; then
      return 0
    fi
    if [ "$fetch_try" -ge 3 ]; then
      return 1
    fi
    echo "attempt $fetch_try for $1 failed; retrying in ${fetch_wait}s" >>"$DOWNLOAD_LOG"
    sleep "$fetch_wait"
    fetch_try=$((fetch_try + 1))
    fetch_wait=$((fetch_wait * 2))
  done
}

fetch_once() {
  # A partial file from a cut-off attempt must never be handed to the next step: the caller
  # untars what it finds here, so a half-download would surface as a corrupt archive rather
  # than as a network problem. Removing it first makes the failure say what it is.
  rm -f "$2"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf --connect-timeout 10 "$1" -o "$2" 2>>"$DOWNLOAD_LOG"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" --connect-timeout=10 "$1" 2>>"$DOWNLOAD_LOG"
  else
    echo "neither curl nor wget is installed" >>"$DOWNLOAD_LOG"
    return 1
  fi
}

# IN-3 — say the useful thing about a TLS-inspecting proxy. Python and Node each need their
# own pointer at the CA bundle, and neither error message names the cause.
proxy_hint_if_certificate() {
  if [ -f "$1" ] && grep -qiE 'certificate|SSL|self.signed' "$1" 2>/dev/null; then
    say ""
    say "This looks like a TLS-inspecting proxy re-signing the connection."
    say "Point curl, Python and Node at your organisation's CA bundle, then run this again:"
    say "  export CURL_CA_BUNDLE=/path/to/ca-bundle.pem"
    say "  export SSL_CERT_FILE=/path/to/ca-bundle.pem"
    say "  export NODE_EXTRA_CA_CERTS=/path/to/ca-bundle.pem"
  fi
}

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

# uv is the one tool the rest cannot install through itself.
ensure_uv() {
  if UV=$(find_uv); then
    return 0
  fi
  say "Installing uv, the Python package manager Aughor uses..."
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
}

check_uv_version() {
  uv_version=$("$UV" --version 2>/dev/null || true)
  uv_version=${uv_version#uv }
  uv_version=${uv_version%% *}
  case "$uv_version" in
    0.[0-7] | 0.[0-7].*)
      fail "uv $uv_version is too old for Aughor." "Update it (uv self update, or your package manager), then run this again."
      ;;
  esac
}

ensure_python() {
  if "$UV" python find "$PYTHON_VERSION" >/dev/null 2>&1 </dev/null; then
    return 0
  fi
  say "Installing Python $PYTHON_VERSION..."
  "$UV" python install "$PYTHON_VERSION" >"$LOGS/python-install.log" 2>&1 </dev/null ||
    fail "Could not install Python $PYTHON_VERSION." "Check your internet connection, then run this again. Log: $LOGS/python-install.log"
  ok "Python $PYTHON_VERSION installed"
}

main "$@"
