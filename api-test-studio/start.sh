#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
test -x .venv/bin/python || python3 -m venv .venv
.venv/bin/python -m pip install --quiet -r requirements.txt
(cd web && npm ci --no-audit --no-fund && npm run build)
echo "API Test Studio is starting on http://127.0.0.1:${PORT:-8000}  (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn studio.main:app --host 127.0.0.1 --port "${PORT:-8000}"
