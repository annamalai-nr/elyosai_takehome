#!/usr/bin/env bash
# Restart the chat backend (WebSocket on :8765) and the static frontend (:8000).
# Logs and PID files are written to .tmp/ (gitignored).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$ROOT_DIR/.tmp"
ENV_NAME="${ELYOS_ENV:-elyosai}"

mkdir -p "$TMP_DIR"

stop_port() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill
  fi
}

stop_port 8765
stop_port 8000

cd "$ROOT_DIR"

nohup conda run -n "$ENV_NAME" --no-capture-output python -m backend.chat --serve \
  > "$TMP_DIR/backend-chat.log" 2>&1 &
echo "$!" > "$TMP_DIR/backend-chat.pid"

nohup conda run -n "$ENV_NAME" --no-capture-output python -m http.server 8000 --directory frontend \
  > "$TMP_DIR/frontend-http.log" 2>&1 &
echo "$!" > "$TMP_DIR/frontend-http.pid"

echo "Backend:  ws://localhost:8765  pid=$(cat "$TMP_DIR/backend-chat.pid")"
echo "Frontend: http://localhost:8000 pid=$(cat "$TMP_DIR/frontend-http.pid")"
