#!/usr/bin/env bash
# Starts the lineage API and UI together; Ctrl+C stops both. A previous run still holding the ports is stopped first.
# Usage: ./start.sh [--check] [--install-only] [--skip-install] [--migrate] [path/to/lineage.db]
#   (no path)       serve every project found in outputs/<project>/lineage.db; choose one in the UI
#   path/to/db      serve only that database
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
DB="${LINEAGE_DB:-}"
OUTPUTS="${LINEAGE_OUTPUTS_DIR:-$ROOT/outputs}"
MIGRATE=0 CHECK=0 INSTALL_ONLY=0 SKIP_INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --migrate) MIGRATE=1 ;;
    --check) CHECK=1 ;;
    --install-only) INSTALL_ONLY=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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
# One fixed database when a path is given, otherwise every outputs/<project>/lineage.db.
db_files() {
  if [ -n "$DB" ]; then [ -f "$DB" ] && echo "$DB"; return 0; fi
  [ -d "$OUTPUTS" ] && find "$OUTPUTS" -mindepth 2 -maxdepth 2 -name lineage.db -type f | sort
  return 0
}
db_exists() { [ -n "$(db_files)" ]; }
db_has_business_process_columns() {
  local file="${1:-$DB}"
  [ -f "$file" ] && venv_ok && "$PYTHON" - "$file" <<'PY'
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
  if ! db_exists; then
    if [ -n "$DB" ]; then show "Database" "NOT FOUND ($DB)"; else show "Databases" "NONE FOUND (expected $OUTPUTS/<project>/lineage.db)"; fi
    bad=1
  else
    local file name
    while IFS= read -r file; do
      if [ -n "$DB" ]; then name="Database"; else name="Project $(basename "$(dirname "$file")")"; fi
      if ! venv_ok; then show "$name" "found ($file)"
      elif db_has_business_process_columns "$file"; then show "$name" "ok ($file)"
      else show "$name" "needs --migrate ($file)"; bad=1; fi
    done < <(db_files)
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

if [ -n "$DB" ]; then
  db_exists || fail "lineage database not found: $DB"
else
  db_exists || fail "no lineage database found: put one at $OUTPUTS/<project>/lineage.db, or pass a path"
fi

# Restart: stop a previous run of this project that still holds a port; refuse to touch anything else.
stop_previous() {
  local port="$1" pid cwd pids=()
  for pid in $(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
    case "$cwd" in
      "$ROOT"|"$ROOT"/*) pids+=("$pid") ;;
      *) fail "port $port is in use by another program (pid $pid); set API_PORT or UI_PORT to use another" ;;
    esac
  done
  [ "${#pids[@]}" -gt 0 ] || return 0
  echo "Restarting: stopping previous process on port $port (pid ${pids[*]})"
  kill "${pids[@]}" 2>/dev/null || true
  for _ in $(seq 1 10); do port_free "$port" && return 0; sleep 0.5; done
  kill -9 "${pids[@]}" 2>/dev/null || true
  sleep 0.5
  port_free "$port" || fail "could not free port $port"
}
for port in "$API_PORT" "$UI_PORT"; do stop_previous "$port"; done

while IFS= read -r file; do
  db_has_business_process_columns "$file" && continue
  if [ "$MIGRATE" -eq 1 ]; then
    echo "Adding business process columns to $file"
    (cd "$API_DIR" && "$PYTHON" -m lineage_api.migrations "$file") || echo "warning: could not migrate $file" >&2
  elif [ -n "$DB" ]; then
    fail "the database has no business_process columns on business_lineage_step. Re-run with --migrate to add them."
  else
    echo "warning: $file needs --migrate; it will show as not ready in the project list" >&2
  fi
done < <(db_files)

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

if [ -n "$DB" ]; then
  export LINEAGE_DB="$DB"; unset LINEAGE_OUTPUTS_DIR
else
  unset LINEAGE_DB; export LINEAGE_OUTPUTS_DIR="$OUTPUTS"
fi
(cd "$API_DIR" && exec "$PYTHON" -m uvicorn lineage_api.app:app \
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
    if [ -n "$DB" ]; then echo "  DB:  $DB"; else echo "  Projects from: $OUTPUTS/<project>/lineage.db ($(db_files | wc -l | tr -d ' ') found)"; fi
    echo "Press Ctrl+C to stop."
    break
  fi
  sleep 1
done

while kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null; do
  sleep 1
done
echo "A service stopped; shutting down the other." >&2
