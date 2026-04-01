#!/bin/bash

# Launch software-like local system: server first, Chromium after.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Run backend in the background and log to file.
nohup "$SCRIPT_DIR/run.sh" > "$SCRIPT_DIR/flask.log" 2>&1 &

# Wait for Flask to start.
sleep 4

# Open Chromium in app/kiosk mode optimised for Waveshare 5-inch HDMI LCD (800×480).
# --kiosk hides all browser UI for a clean kiosk experience.
# --window-size ensures the window matches the display resolution exactly.
chromium-browser \
  --app=http://127.0.0.1:5000 \
  --kiosk \
  --window-size=800,480 \
  --disable-infobars \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --check-for-update-interval=31536000
