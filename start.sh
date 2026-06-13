#!/bin/bash
# Start the Aughor backend + frontend from any directory.
# Usage: ./start.sh              — API (:8000) + web (:3000), both in background
#        ./start.sh --api-only   — API only, background, logs to /tmp/aughor-api.log
#        ./start.sh --web-only   — web only, foreground
#        ./start.sh --stop       — stop both processes

set -e

AUGHOR_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$AUGHOR_DIR/web"
API_LOG="/tmp/aughor-api.log"
API_PID="/tmp/aughor-api.pid"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

start_api() {
  # SIGKILL (not TERM): a --reload worker blocked on open SSE/exploration connections
  # ignores a graceful TERM and holds :8000, so a plain pkill can't restart it.
  pkill -9 -f "uvicorn aughor.api" 2>/dev/null || true
  sleep 0.5
  cd "$AUGHOR_DIR"
  # --timeout-graceful-shutdown bounds the wait so an in-flight reload can't hang
  # forever on long-lived SSE streams (the recurring dev wedge).
  nohup uv run uvicorn aughor.api:app --port 8000 --reload --timeout-graceful-shutdown 3 > "$API_LOG" 2>&1 &
  echo $! > "$API_PID"
  echo "API started (pid $!, logs: $API_LOG)"
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
    pkill -f "uvicorn aughor.api" 2>/dev/null && echo "API stopped" || echo "API was not running"
    pkill -f "next dev"           2>/dev/null && echo "Web stopped" || echo "Web was not running"
    ;;
  *)
    start_api
    echo "Starting web on :3000 ..."
    start_web
    ;;
esac
