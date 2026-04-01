#!/bin/bash

# Launch software-like local system: server first, Chromium after.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Run backend in the background and log to file.
nohup "$SCRIPT_DIR/run.sh" > "$SCRIPT_DIR/flask.log" 2>&1 &

# Wait for Flask to start.
sleep 4

# Open Chromium in app mode. Change to --kiosk for strict kiosk mode.
chromium-browser --app=http://127.0.0.1:5000 --start-fullscreen
