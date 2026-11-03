#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import fastapi, uvicorn, pandas, numpy, httpx" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
# A working frontend build is included; Node is only needed to rebuild UI source.
if [ ! -f dist/index.html ]; then
  npm ci
  npm run build
fi
# Participant UI (Next.js static export). Built once per checkout.
if [ ! -f web/out/index.html ]; then
  (cd web && npm ci && npm run build)
fi
unset TRACE_LEGACY_AUTH TRACE_ACCESS_FILE
trace_port="${TRACE_PORT:-8001}"
printf '\nTRACE: http://127.0.0.1:%s/?research=1\nPress Ctrl+C to stop.\n' "$trace_port"
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "$trace_port"
