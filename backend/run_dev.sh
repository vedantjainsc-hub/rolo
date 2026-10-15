#!/usr/bin/env bash
# Start the Rolo backend on 0.0.0.0:8000. Creates backend/.venv on first run.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Creating virtualenv in backend/.venv ..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
