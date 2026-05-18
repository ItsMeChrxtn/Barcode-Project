#!/bin/bash

set -euo pipefail

# Launch software-like local system: server first, Chromium after.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
APP_URL="http://127.0.0.1:5000"

is_server_ready() {
  if command -v curl >/dev/null 2>&1; then
    curl --silent --fail "$APP_URL/healthz" >/dev/null 2>&1
    return $?
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null "$APP_URL/healthz" >/dev/null 2>&1
    return $?
  fi

  return 1
}

resolve_chromium_command() {
  if command -v chromium-browser >/dev/null 2>&1; then
    echo "chromium-browser"
    return 0
  fi

  if command -v chromium >/dev/null 2>&1; then
    echo "chromium"
    return 0
  fi

  return 1
}

# Run backend in the background only if not yet running.
if ! is_server_ready; then
  nohup "$SCRIPT_DIR/run.sh" > "$SCRIPT_DIR/flask.log" 2>&1 &
fi

# Wait up to ~45 seconds for Flask startup.
max_attempts=45
attempt=0
until is_server_ready; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "[ERROR] Flask server did not become ready in time."
    echo "Check log: $SCRIPT_DIR/flask.log"
    exit 1
  fi
  sleep 1
done

CHROMIUM_CMD="$(resolve_chromium_command || true)"
if [ -z "$CHROMIUM_CMD" ]; then
  echo "[ERROR] Chromium not found. Install chromium-browser or chromium package."
  exit 1
fi

# Open Chromium in app window mode and let it use the native resolution of the connected display.
"$CHROMIUM_CMD" \
  --app="$APP_URL" \
  --disable-infobars \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000
