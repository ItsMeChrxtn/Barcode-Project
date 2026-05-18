#!/bin/bash

set -euo pipefail

# Raspberry Pi launcher entrypoint. This replaces RUN_APP.bat for Linux devices.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 is not installed."
  echo "Install dependencies first: sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "[INFO] No .venv found. Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "[INFO] Installing Python dependencies from requirements.txt..."
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
  else
    echo "[WARN] requirements.txt not found. Continuing without dependency install."
  fi
else
  echo "[INFO] Existing .venv detected. Skipping setup."
fi

if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  echo "[ERROR] curl or wget is required for health checks."
  echo "Install one of them: sudo apt install -y curl"
  exit 1
fi

if ! command -v chromium-browser >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1; then
  echo "[ERROR] Chromium is not installed."
  echo "Install it with: sudo apt install -y chromium-browser || sudo apt install -y chromium"
  exit 1
fi

chmod +x "$SCRIPT_DIR/run.sh" "$SCRIPT_DIR/launch_system.sh"
exec "$SCRIPT_DIR/launch_system.sh"
