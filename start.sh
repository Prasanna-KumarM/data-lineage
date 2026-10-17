#!/usr/bin/env bash
# Starts the lineage API and UI together; Ctrl+C stops both.
# Usage: ./start.sh [--check] [--install-only] [--skip-install] [--migrate] [path/to/lineage.db]
#   --check         report what is installed and ready, then exit
#   --install-only  install missing Python/UI packages, then exit
#   --skip-install  never install anything; fail if something is missing
#   --migrate       add the business_process columns to the database when they are missing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"
API_DIR="$ROOT/src/api"
UI_DIR="$ROOT/src/ui"
API_REQUIREMENTS="$API_DIR/requirements.txt"
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"
DB="${LINEAGE_DB:-$ROOT/outputs/SP_CLO/lineage.db}"
MIGRATE=0 CHECK=0 INSTALL_ONLY=0 SKIP_INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --migrate) MIGRATE=1 ;;
    --check) CHECK=1 ;;
    --install-only) INSTALL_ONLY=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "error: unknown option $arg" >&2; exit 1 ;;
    *) DB="$arg" ;;
  esac
done

fail() { echo "error: $*" >&2; exit 1; }

# --- state checks -------------------------------------------------------------------------

venv_ok() { [ -x "$PYTHON" ]; }
python_deps_ok() { venv_ok && "$PYTHON" -c "import fastapi, uvicorn" 2>/dev/null; }
# git rewrites package-lock.json on checkout, so staleness is judged by its content, not its timestamp.
UI_LOCK_MARKER="$UI_DIR/node_modules/.lineage-lock-hash"
lock_hash() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$UI_DIR/package-lock.json"; else sha256sum "$UI_DIR/package-lock.json"; fi | cut -d' ' -f1; }
ui_deps_ok() {
  [ -x "$UI_DIR/node_modules/.bin/vite" ] || return 1
  [ -f "$UI_DIR/package-lock.json" ] || return 0
  if [ -f "$UI_LOCK_MARKER" ]; then
    [ "$(cat "$UI_LOCK_MARKER")" = "$(lock_hash)" ]
  else
    # Installed before the marker existed: trust npm's own check once, then remember the result.
    (cd "$UI_DIR" && npm ls --depth=0 >/dev/null 2>&1) && lock_hash > "$UI_LOCK_MARKER"
  fi
}
port_free() { ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
db_exists() { [ -f "$DB" ]; }
db_has_business_process_columns() {
  db_exists && venv_ok && "$PYTHON" - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
cols = {r[1] for r in con.execute("PRAGMA table_info(business_lineage_step)")}
sys.exit(0 if {"business_process_id", "business_process_name"} <= cols else 3)
PY
}

report() {
  local bad=0 line
  show() { printf '  %-22s %s\n' "$1" "$2"; }
  echo "Environment"
  if venv_ok; then show "Python environment" "ok ($("$PYTHON" --version 2>&1))"; else show "Python environment" "missing (will create .venv)"; bad=1; fi
  if python_deps_ok; then show "API packages" "ok"; else show "API packages" "missing (will install from src/api/requirements.txt)"; bad=1; fi
  if command -v node >/dev/null 2>&1; then show "Node.js" "ok ($(node --version))"; else show "Node.js" "MISSING (install Node 18 or newer)"; bad=1; fi
  if ui_deps_ok; then show "UI packages" "ok"
  elif [ -d "$UI_DIR/node_modules" ]; then show "UI packages" "out of date (will run npm ci)"; bad=1
  else show "UI packages" "missing (will run npm ci)"; bad=1; fi
  echo "Data"
  if db_exists; then show "Database" "ok ($DB)"; else show "Database" "NOT FOUND ($DB)"; bad=1; fi
  if venv_ok && db_exists; then
    if db_has_business_process_columns; then show "business_process cols" "ok"
    elif db_exists; then show "business_process cols" "missing (use --migrate)"; bad=1; fi
  fi
  echo "Ports"
  for line in "API:$API_PORT" "UI:$UI_PORT"; do
    if port_free "${line#*:}"; then show "${line%%:*} port ${line#*:}" "free"; else show "${line%%:*} port ${line#*:}" "IN USE"; bad=1; fi
  done
  return $bad
}

# --- installation -------------------------------------------------------------------------

ensure_python_env() {
  if ! venv_ok; then
    command -v python3 >/dev/null || fail "python3 is required to create the virtual environment"
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || fail "Python 3.10 or newer is required"
    echo "Creating virtual environment in .venv"
    python3 -m venv "$VENV"
  fi
  if ! python_deps_ok; then
    [ -f "$API_REQUIREMENTS" ] || fail "missing $API_REQUIREMENTS"
    echo "Installing API packages from src/api/requirements.txt"
    "$PYTHON" -m pip install -q -r "$API_REQUIREMENTS"
  fi
}

ensure_ui_packages() {
  command -v node >/dev/null && command -v npm >/dev/null || fail "Node.js and npm are required for the UI (Node 18 or newer)"
  if ! ui_deps_ok; then
    echo "Installing UI packages (npm ci)"
    if [ -f "$UI_DIR/package-lock.json" ]; then (cd "$UI_DIR" && npm ci); else (cd "$UI_DIR" && npm install); fi
    [ -f "$UI_DIR/package-lock.json" ] && lock_hash > "$UI_LOCK_MARKER"
  fi
}

if [ "$CHECK" -eq 1 ]; then
  if report; then echo "Everything is ready."; exit 0; else echo "Something needs attention (see above)."; exit 1; fi
fi

if [ "$SKIP_INSTALL" -eq 1 ]; then
  python_deps_ok || fail "API packages are missing (run without --skip-install, or: .venv/bin/pip install -r src/api/requirements.txt)"
  ui_deps_ok || fail "UI packages are missing or out of date (run without --skip-install, or: cd src/ui && npm ci)"
else
  ensure_python_env
  ensure_ui_packages
fi

if [ "$INSTALL_ONLY" -eq 1 ]; then
  echo "Dependencies are installed."
  exit 0
fi

# --- start --------------------------------------------------------------------------------

db_exists || fail "lineage database not found: $DB"
for port in "$API_PORT" "$UI_PORT"; do
  port_free "$port" || fail "port $port is already in use (set API_PORT or UI_PORT to use another)"
done

if ! db_has_business_process_columns; then
  if [ "$MIGRATE" -eq 1 ]; then
    echo "Adding business process columns to $DB"
    (cd "$API_DIR" && "$PYTHON" -m lineage_api.migrations "$DB")
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

(cd "$API_DIR" && LINEAGE_DB="$DB" exec "$PYTHON" -m uvicorn lineage_api.app:app \
  --host 127.0.0.1 --port "$API_PORT" --reload) &
PIDS+=("$!")
API_PID="$!"

(cd "$UI_DIR" && LINEAGE_API_URL="http://127.0.0.1:$API_PORT" exec ./node_modules/.bin/vite \
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
