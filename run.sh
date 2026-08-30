#!/usr/bin/env bash
# One-command start. Creates a venv if needed, installs deps, runs the server.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || source .venv/Scripts/activate
pip install -q -r requirements.txt
echo "ControlPlane on http://127.0.0.1:8000  (dashboard at /, API docs at /docs)"
exec uvicorn controlplane.app:app --port 8000
