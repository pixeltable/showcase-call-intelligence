#!/usr/bin/env bash
# Monorepo side-by-side comparison stack.
#
# Reference (Celery + Postgres): http://localhost:5173 → API :8001
# Pixeltable:                  http://localhost:5174 → API :8000
#
# Usage:
#   ./scripts/run_compare.sh         # start everything
#   ./scripts/run_compare.sh seed    # generate/prepare/fetch fixtures + reset DBs + upload
#   ./scripts/run_compare.sh stop
#
# Stop kills only PIDs recorded under .compare-pids/.
# COMPARE_FORCE_PORTS=1 also SIGKILLs anything on 8000/8001/5173/5174.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="${ROOT}/.compare-pids"
DATA_DIR="${ROOT}/data"
export PIXELTABLE_HOME="${PIXELTABLE_HOME:-${DATA_DIR}/pixeltable}"
export UPLOAD_DIR="${UPLOAD_DIR:-${DATA_DIR}/reference/uploads}"
mkdir -p "$PID_DIR" "$PIXELTABLE_HOME" "$UPLOAD_DIR"

stop_all() {
  echo "Stopping comparison stack..."
  for f in "$PID_DIR"/*.pid; do
    [[ -f "$f" ]] || continue
    pid=$(cat "$f")
    if [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  done
  if [[ "${COMPARE_FORCE_PORTS:-}" == "1" ]]; then
    lsof -ti:8000,8001,5173,5174 2>/dev/null | xargs kill -9 2>/dev/null || true
  fi
  echo "Done."
}

if [[ "${1:-}" == "stop" ]]; then
  stop_all
  exit 0
fi

if [[ "${1:-}" == "seed" ]]; then
  cd "$ROOT" && uv run python scripts/seed_compare.py
  exit $?
fi

stop_all

echo "=== Monorepo side-by-side comparison ==="
echo "  Reference:  http://localhost:5173  (API :8001)"
echo "  Pixeltable: http://localhost:5174  (API :8000)"
echo ""

echo "Starting docker services…"
if ! (cd "$ROOT" && docker compose up -d 2>/dev/null); then
  echo "Docker compose skipped (ports may already be in use — using existing Postgres/Redis/Ollama)."
fi

echo "Running reference migrations…"
(cd "$ROOT/backends/reference" && uv run alembic upgrade head)

echo "Starting reference API on :8001…"
(cd "$ROOT/backends/reference" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8001) &
ref_api_pid=$!
echo "$ref_api_pid" > "$PID_DIR/ref-api.pid"

echo "Starting reference Celery worker…"
(cd "$ROOT/backends/reference" && uv run celery -A worker.celery_app worker -l info -n ref@%h -c 1) &
ref_celery_pid=$!
echo "$ref_celery_pid" > "$PID_DIR/ref-celery.pid"

echo "Starting Pixeltable API on :8000…"
(cd "$ROOT/backends/pixeltable" && uv run uvicorn main:app --host 127.0.0.1 --port 8000) &
pxt_api_pid=$!
echo "$pxt_api_pid" > "$PID_DIR/pxt-api.pid"

echo "Starting Reference UI on :5173…"
(cd "$ROOT/frontend" && VITE_API_PORT=8001 VITE_DEV_PORT=5173 npm run dev) &
ref_vite_pid=$!
echo "$ref_vite_pid" > "$PID_DIR/ref-vite.pid"

echo "Starting Pixeltable UI on :5174…"
(cd "$ROOT/frontend" && VITE_API_PORT=8000 VITE_DEV_PORT=5174 VITE_BACKEND=pixeltable npm run dev) &
pxt_vite_pid=$!
echo "$pxt_vite_pid" > "$PID_DIR/pxt-vite.pid"

sleep 4
echo ""
echo "Ready:"
echo "  Reference:  http://localhost:5173"
echo "  Pixeltable: http://localhost:5174"
echo ""
echo "Seed fixtures: ./scripts/run_compare.sh seed   # generate/prepare/fetch + validate + upload"
echo "Parity check:  uv run python scripts/compare_parity.py"
echo "Note: Reference search needs Celery worker + completed calls with transcript segments."
echo "Stop:          ./scripts/run_compare.sh stop"

wait
