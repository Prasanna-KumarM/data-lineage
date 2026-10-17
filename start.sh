#!/usr/bin/env bash
# Starts the lineage API and UI together; Ctrl+C stops both.
# Usage: ./start.sh [--migrate] [path/to/lineage.db]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"
MIGRATE=0
DB="${LINEAGE_DB:-$ROOT/outputs/SP_CLO/lineage.db}"

for arg in "$@"; do
  case "$arg" in
    --migrate) MIGRATE=1 ;;
    -h|--help) sed -n '2,3p' "$0" | sed 's/^# //'; exit 0 ;;
    *) DB="$arg" ;;
  esac
done

fail() { echo "error: $*" >&2; exit 1; }

[ -x "$PYTHON" ] || fail "virtual environment missing. Run: python3 -m venv .venv && .venv/bin/pip install -r src/api/requirements.txt"
"$PYTHON" -c "import fastapi, uvicorn" 2>/dev/null || fail "API dependencies missing. Run: .venv/bin/pip install -r src/api/requirements.txt"
[ -f "$DB" ] || fail "lineage database not found: $DB"
command -v node >/dev/null || fail "Node.js is required for the UI"

for port in "$API_PORT" "$UI_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "port $port is already in use (set API_PORT or UI_PORT to use another)"
  fi
done

[ -d "$ROOT/src/ui/node_modules" ] || (cd "$ROOT/src/ui" && npm ci)

has_business_process_columns() {
  "$PYTHON" - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
cols = {r[1] for r in con.execute("PRAGMA table_info(business_lineage_step)")}
sys.exit(0 if {"business_process_id", "business_process_name"} <= cols else 3)
PY
}

if ! has_business_process_columns; then
  if [ "$MIGRATE" -eq 1 ]; then
    echo "Adding business process columns to $DB"
    (cd "$ROOT/src/api" && "$PYTHON" -m lineage_api.migrations "$DB")
  else
    fail "the database has no business_process columns on business_lineage_step. Re-run with --migrate to add them."
  fi
fi

PIDS=()
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping services..."
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(cd "$ROOT/src/api" && LINEAGE_DB="$DB" exec "$PYTHON" -m uvicorn lineage_api.app:app \
  --host 127.0.0.1 --port "$API_PORT" --reload) &
PIDS+=("$!")
API_PID="$!"

(cd "$ROOT/src/ui" && LINEAGE_API_URL="http://127.0.0.1:$API_PORT" exec ./node_modules/.bin/vite \
  --host 127.0.0.1 --port "$UI_PORT" --strictPort) &
PIDS+=("$!")
UI_PID="$!"

for _ in $(seq 1 30); do
  if curl -fs "http://127.0.0.1:$API_PORT/projects" >/dev/null 2>&1 && curl -fs "http://127.0.0.1:$UI_PORT/" >/dev/null 2>&1; then
    echo
    echo "Data Lineage is running"
    echo "  UI:  http://127.0.0.1:$UI_PORT/"
    echo "  API: http://127.0.0.1:$API_PORT/docs"
    echo "  DB:  $DB"
    echo "Press Ctrl+C to stop."
    break
  fi
  sleep 1
done

while kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null; do
  sleep 1
done
echo "A service stopped; shutting down the other." >&2
