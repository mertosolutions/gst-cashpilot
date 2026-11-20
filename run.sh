#!/usr/bin/env bash
# Starts the FastAPI backend (port 8010) and the Next.js web app (port 3000).
set -e
cd "$(dirname "$0")"
[ -d api/.venv ] || { python3 -m venv api/.venv && api/.venv/bin/pip install -q -r api/requirements.txt; }
[ -d web/node_modules ] || (cd web && npm install)
(cd api && .venv/bin/uvicorn app.main:app --port 8010 --reload) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
(cd web && npm run dev)
