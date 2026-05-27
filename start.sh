#!/usr/bin/env bash
# LawPrep — one-command launcher.
# - Creates a venv on first run
# - Installs requirements
# - Starts the Flask app on http://127.0.0.1:5050

set -e

cd "$(dirname "$0")"

echo "============================================"
echo "  MH-CET Law 2026 — LawPrep Portal"
echo "============================================"

# Pick a python
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Error: $PY not found. Install Python 3.10+ from https://www.python.org/downloads/" >&2
    exit 1
fi

# Create venv on first run
if [ ! -d "venv" ]; then
    echo "Creating virtual environment (venv/)..."
    "$PY" -m venv venv
fi

# Activate venv
# shellcheck source=/dev/null
source venv/bin/activate

# Install / update requirements (quiet unless something goes wrong)
echo "Checking dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Suggest creating .env if missing
if [ ! -f ".env" ]; then
    echo
    echo "Note: no .env file found. The portal will run, but optional AI"
    echo "and TTS features will be disabled. To enable them, run:"
    echo "    cp .env.example .env"
    echo "and add your API keys."
    echo
fi

echo
echo "Starting portal at http://127.0.0.1:5050"
echo "Press Ctrl+C to stop."
echo
exec python app/app.py
