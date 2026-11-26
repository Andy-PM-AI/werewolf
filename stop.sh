#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$ROOT/.run/api.pid" ]; then
  PID=$(cat "$ROOT/.run/api.pid")
  if kill "$PID" 2>/dev/null; then
    echo "Stopped API (pid $PID)"
  else
    echo "API process $PID is not running"
  fi
  rm -f "$ROOT/.run/api.pid"
else
  pkill -f "$ROOT/backend/server.py" 2>/dev/null || true
  echo "No pid file; stopped any matching server process"
fi
