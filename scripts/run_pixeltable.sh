#!/usr/bin/env bash
# The core lesson: one Pixeltable service, one UI, and the shared local Ollama service.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"
set +a
export PIXELTABLE_HOME="$ROOT/data/lesson/pixeltable" PXT_UPLOAD_DIR="$ROOT/data/lesson/uploads"
export PXT_ENRICHMENT_PROFILE=core PIXELTABLE_TIME_ZONE=UTC
export PXT_PORT="${PXT_LESSON_PORT:-22091}"
export PXT_API_PORT="${PXT_LESSON_API_PORT:-8002}" PXT_UI_PORT="${PXT_LESSON_UI_PORT:-5175}"
export PXT_API="http://127.0.0.1:$PXT_API_PORT"
PXT_DIR="$ROOT/backends/pixeltable"
mkdir -p "$PIXELTABLE_HOME" "$PXT_UPLOAD_DIR"
pxt() { (cd "$PXT_DIR" && uv run --frozen pxt "$@"); }

case "${1:-up}" in
  up)
    # Refuse a port owned by a different home instead of replacing its daemon.
    uv run --frozen python - "$PXT_PORT" "$PIXELTABLE_HOME" <<'PY'
import os, pathlib, socket, sys
port, home = int(sys.argv[1]), pathlib.Path(sys.argv[2])
with socket.socket() as listener:
    try:
        listener.bind(('127.0.0.1', port))
    except OSError:
        marker = home / f'pxt-daemon-{port}.pid'
        try:
            os.kill(int(marker.read_text()), 0)
        except (OSError, ValueError):
            raise SystemExit(f'Daemon port {port} is occupied. Choose PXT_LESSON_PORT for this lesson.')
PY
    (cd "$ROOT" && docker compose up -d ollama)
    pxt daemon restart
    pxt schema check app.py
    pxt schema update app.py first_lesson -f
    pxt service update app.py first_lesson --port "$PXT_API_PORT" -f
    echo "Add one six-second fixture in another terminal: ./scripts/run_pixeltable.sh seed"
    if [[ "${NO_UI:-0}" != "1" ]]; then
      echo "Lesson UI: http://localhost:$PXT_UI_PORT"
      cd "$ROOT/frontend"
      exec env VITE_API_PORT="$PXT_API_PORT" VITE_DEV_PORT="$PXT_UI_PORT" npm run dev
    fi
    ;;
  seed)
    (cd "$ROOT" && uv run --frozen python scripts/seed_pixeltable.py)
    ;;
  extend)
    (cd "$PXT_DIR" && uv run --frozen python "$ROOT/examples/extend_call.py")
    ;;
  stop)
    if [[ -f "$PIXELTABLE_HOME/pxt-daemon-$PXT_PORT.pid" ]]; then
      pxt service stop first_lesson/api
      pxt daemon stop
    fi
    echo "Lesson service stopped; data kept. Press Ctrl-C in the UI terminal. Shared Ollama remains available."
    ;;
  *) echo "usage: $0 [up|seed|extend|stop]" >&2; exit 2 ;;
esac
