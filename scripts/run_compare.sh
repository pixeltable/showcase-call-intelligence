#!/usr/bin/env bash
# Both stacks side by side.
#
#   ./scripts/run_compare.sh          # start everything (UIs included unless NO_UI=1)
#   ./scripts/run_compare.sh seed     # reset both stores and ingest the 10 fixtures
#   ./scripts/run_compare.sh stop     # stop what this script started; data is kept
#
# Reference:  UI :$REF_UI_PORT -> API :$REF_API_PORT (FastAPI + Celery + Redis + Postgres/pgvector)
# Pixeltable: UI :$PXT_UI_PORT -> API :$PXT_API_PORT (`pxt service`, app.py)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.compare-pids"
mkdir -p "$PID_DIR"

# .env values reach both backends through the environment. The pxt daemon reads its configuration
# once at startup, so it must see them before the first `pxt` command.
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a

export REF_API_PORT="${REF_API_PORT:-8001}" PXT_API_PORT="${PXT_API_PORT:-8000}"
export REF_UI_PORT="${REF_UI_PORT:-5173}" PXT_UI_PORT="${PXT_UI_PORT:-5174}"
export REF_API="http://127.0.0.1:$REF_API_PORT" PXT_API="http://127.0.0.1:$PXT_API_PORT"
export PIXELTABLE_HOME="$ROOT/data/pixeltable" PXT_UPLOAD_DIR="$ROOT/data/pixeltable/uploads"
export UPLOAD_DIR="$ROOT/data/reference/uploads" PIXELTABLE_TIME_ZONE="${PIXELTABLE_TIME_ZONE:-UTC}"
# A daemon port of this repo's own: pxt replaces a daemon that serves another project on its port.
export PXT_PORT="${PXT_PORT:-22090}"
export PXT_ENRICHMENT_PROFILE=full
mkdir -p "$PIXELTABLE_HOME" "$PXT_UPLOAD_DIR" "$UPLOAD_DIR"

PXT_DIR="$ROOT/backends/pixeltable"
REF_DIR="$ROOT/backends/reference"
pxt() { (cd "$PXT_DIR" && uv run --quiet pxt "$@"); }

start_bg() {  # name, dir, command...
  local name="$1" dir="$2"
  shift 2
  (cd "$dir" && exec "$@") >"$PID_DIR/$name.log" 2>&1 &
  echo $! >"$PID_DIR/$name.pid"
}

stop_all() {
  for f in "$PID_DIR"/*.pid; do
    [[ -f "$f" ]] || continue
    pid="$(cat "$f")"
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] && kill "$pid" 2>/dev/null || true
    rm -f "$f"
  done
  pxt service stop call_center/api >/dev/null 2>&1 || true
}

wait_healthy() {  # url, seconds. Health answers 200 even when degraded, so wait for "ok" itself.
  for _ in $(seq "$2"); do
    curl -fs "$1/api/health" 2>/dev/null | grep -q '"status":"ok"' && return 0
    sleep 1
  done
  echo "not healthy after $2s: $1 $(curl -s "$1/api/health" 2>/dev/null)" >&2
  return 1
}

start_pixeltable() {
  pxt daemon restart >/dev/null
  pxt schema update app.py call_center -f
  pxt service update app.py call_center --port "$PXT_API_PORT" -f
}

case "${1:-up}" in
  stop)
    stop_all
    echo "Stopped. Data is kept under data/ and in the Docker volumes."
    ;;
  seed)
    cd "$ROOT" && uv run python scripts/seed_compare.py
    ;;
  up)
    stop_all
    (cd "$ROOT" && docker compose up -d)
    (cd "$REF_DIR" && uv run alembic upgrade head)
    start_bg ref-api "$REF_DIR" uv run uvicorn app.main:app --host 127.0.0.1 --port "$REF_API_PORT"
    start_bg ref-celery "$REF_DIR" uv run celery -A worker.celery_app worker -l info -n "ref@%h" -c 1
    start_pixeltable
    wait_healthy "$REF_API" 60
    wait_healthy "$PXT_API" 60
    if [[ "${NO_UI:-0}" != "1" ]]; then
      start_bg ref-ui "$ROOT/frontend" env VITE_API_PORT="$REF_API_PORT" VITE_DEV_PORT="$REF_UI_PORT" npm run dev
      start_bg pxt-ui "$ROOT/frontend" env VITE_API_PORT="$PXT_API_PORT" VITE_DEV_PORT="$PXT_UI_PORT" npm run dev
      echo "Reference:  http://localhost:$REF_UI_PORT"
      echo "Pixeltable: http://localhost:$PXT_UI_PORT"
    fi
    echo "APIs: $REF_API (reference), $PXT_API (pixeltable). Seed: ./scripts/run_compare.sh seed"
    ;;
  *)
    echo "usage: $0 [up|seed|stop]" >&2
    exit 2
    ;;
esac
