#!/bin/bash
# Start the Hermes backend + frontend from any directory.
# Usage: ./start.sh              — API (:8000) + web (:3000), both in background
#        ./start.sh --api-only   — API only, background, logs to /tmp/hermes-api.log
#        ./start.sh --web-only   — web only, foreground
#        ./start.sh --stop       — stop both processes

set -e

HERMES_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$HERMES_DIR/web"
API_LOG="/tmp/hermes-api.log"
API_PID="/tmp/hermes-api.pid"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

start_api() {
  pkill -f "uvicorn hermes.api" 2>/dev/null || true
  sleep 0.5
  cd "$HERMES_DIR"
  nohup uv run uvicorn hermes.api:app --port 8000 --reload > "$API_LOG" 2>&1 &
  echo $! > "$API_PID"
  echo "API started (pid $!, logs: $API_LOG)"
  # Wait briefly and confirm it's up
  sleep 2
  if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "API healthy ✓"
  else
    echo "API may still be starting — check $API_LOG"
  fi
}

start_web() {
  cd "$WEB_DIR" && npm run dev
}

case "${1:-}" in
  --api-only)
    start_api
    ;;
  --web-only)
    pkill -f "next dev" 2>/dev/null || true
    start_web
    ;;
  --stop)
    pkill -f "uvicorn hermes.api" 2>/dev/null && echo "API stopped" || echo "API was not running"
    pkill -f "next dev"           2>/dev/null && echo "Web stopped" || echo "Web was not running"
    ;;
  *)
    start_api
    echo "Starting web on :3000 ..."
    start_web
    ;;
esac
