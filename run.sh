#!/usr/bin/env bash
# One command from a fresh clone to a working screen.
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
python -m pip install -q -r requirements.txt

[ -f data/incident.json ] || python tools/normalise.py

echo
echo "  mock mode (0 tokens) is the default. export MOCK=0 for a live run."
echo "  http://${HOST:-127.0.0.1}:${PORT:-8000}/          the interface"
echo "  http://${HOST:-127.0.0.1}:${PORT:-8000}/?demo     a recorded run, no backend needed"
echo
exec python -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
