#!/bin/bash

set -euo pipefail

# Start Flask app on local Raspberry Pi network interface.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
REQ_MARKER="$VENV_DIR/.requirements.installed"
DB_FILE="$SCRIPT_DIR/database.db"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

# Install Python dependencies only when needed.
if [ ! -f "$REQ_MARKER" ] || [ "$REQ_FILE" -nt "$REQ_MARKER" ]; then
  "$VENV_PYTHON" -m pip install --quiet --upgrade pip
  "$VENV_PYTHON" -m pip install --quiet -r "$REQ_FILE"
  touch "$REQ_MARKER"
fi

if [ ! -f "$DB_FILE" ]; then
  "$VENV_PYTHON" init_db.py
  "$VENV_PYTHON" seed_data.py
else
  "$VENV_PYTHON" init_db.py
fi

export FLASK_APP=app.py
export FLASK_ENV=production
export FLASK_HOST="${FLASK_HOST:-0.0.0.0}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

exec "$VENV_PYTHON" app.py
