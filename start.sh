#!/bin/bash
# Thin shim over `uv run aughor up` — kept for muscle memory.
# Usage: ./start.sh                    — API (:8000) + web (:3000), foreground, Ctrl-C stops both
#        ./start.sh --api-only         — API only
#        ./start.sh --web-only         — web only
#        ./start.sh --dev              — API with auto-reload
#        ./start.sh --api-port 8010 --web-port 3010
#        ./start.sh --stop             — stop stray background processes (graceful TERM)
#
# `aughor up` never kills a busy port's owner — it reports who holds the port and
# exits so you can stop it yourself or pick another port.

set -e

AUGHOR_DIR="$(cd "$(dirname "$0")" && pwd)"

# npm may live behind nvm in interactive shells; make it available here too.
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

if [ "${1:-}" = "--stop" ]; then
  # `pkill -f` matches ANY process whose command line contains the pattern. "next dev"
  # alone also matched the shell running this script, an editor with that text in its
  # arguments, and a grep for it — a --stop that kills the terminal you typed it in.
  # The bracket form stops the pkill from matching itself, but nothing else; anchoring on
  # this checkout's path is what makes the match specific, and it also stops one clone's
  # --stop from killing a sibling clone's servers. -u confines the sweep to this user.
  pkill -u "$(id -u)" -f "^.*${AUGHOR_DIR}.*[u]vicorn aughor\.api" 2>/dev/null \
    && echo "API stopped" || echo "API was not running"
  pkill -u "$(id -u)" -f "^.*${AUGHOR_DIR}/web.*[n]ext dev" 2>/dev/null \
    && echo "Web stopped" || echo "Web was not running"
  exit 0
fi

cd "$AUGHOR_DIR"
exec uv run aughor up "$@"
