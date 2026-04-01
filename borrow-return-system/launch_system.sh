#!/bin/bash

# Launch software-like local system: server first, Chromium after.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Run backend in the background and log to file.
nohup "$SCRIPT_DIR/run.sh" > "$SCRIPT_DIR/flask.log" 2>&1 &

# Wait for Flask to start.
sleep 4

# Open Chromium in kiosk mode and let it use the native resolution of the connected display.
# --kiosk hides all browser UI for a clean kiosk experience.
chromium-browser \
  --app=http://127.0.0.1:5000 \
  --kiosk \
  --disable-infobars \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000
