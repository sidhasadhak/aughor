#!/bin/zsh
# Headless capture of one Aughor screen, the way the 2026-09-25 UI/UX study took its figures.
#   usage: capture.sh <outdir> <width> <height> <name> <url>
# Rules that cost a session to learn: use a FRESH --user-data-dir (the launch is otherwise swallowed by a
# running Chrome, and a killed run leaves a SingletonLock); use --timeout, never --virtual-time-budget (it
# never settles against the Next dev server's live socket); wrap in an alarm — Chrome does not always exit.
set -u
out=$1; w=$2; h=$3; name=$4; url=$5
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
prof=$(mktemp -d)
perl -e 'alarm 40; exec @ARGV' "$CH" --headless=new --disable-gpu --hide-scrollbars --no-first-run \
  --no-default-browser-check --user-data-dir="$prof" --force-device-scale-factor=2 --timeout=10000 \
  --window-size="$w,$h" --screenshot="$out/$name.png" "$url" >/dev/null 2>&1
rm -rf "$prof"
[ -s "$out/$name.png" ] && echo "OK $name" || echo "MISS $name"
