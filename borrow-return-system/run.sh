#!/bin/bash

# Start Flask app on local Raspberry Pi network interface.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

python3 init_db.py
python3 seed_data.py

export FLASK_APP=app.py
export FLASK_ENV=production

python3 app.py
