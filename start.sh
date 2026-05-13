#!/bin/bash
# Start the Hermes backend + frontend from any directory.
# Usage: ./start.sh
#        ./start.sh --api-only
#        ./start.sh --web-only

set -e

HERMES_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$HERMES_DIR/web"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

stop_existing() {
  pkill -f "uvicorn hermes.api" 2>/dev/null || true
  pkill -f "next dev"            2>/dev/null || true
}

case "${1:-}" in
  --api-only)
    stop_existing
    echo "Starting API..."
    cd "$HERMES_DIR" && uv run uvicorn hermes.api:app --port 8000 --reload
    ;;
  --web-only)
    stop_existing
    echo "Starting web..."
    cd "$WEB_DIR" && npm run dev
    ;;
  *)
    stop_existing
    echo "Starting API on :8000 and web on :3000 ..."
    cd "$HERMES_DIR" && uv run uvicorn hermes.api:app --port 8000 --reload &
    cd "$WEB_DIR"    && npm run dev
    ;;
esac
