#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORT="${WEREWOLF_PORT:-8791}"
mkdir -p "$ROOT/.run"

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "Frontend build missing, building first..."
  "$ROOT/build.sh"
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "API already listening on http://127.0.0.1:$PORT"
else
  nohup env WEREWOLF_PORT="$PORT" python3 "$ROOT/backend/server.py" >"$ROOT/.run/api.log" 2>&1 &
  echo $! >"$ROOT/.run/api.pid"
  i=0
  while [ "$i" -lt 30 ] && ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do
    sleep 0.5
    i=$((i + 1))
  done
  if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    cat "$ROOT/.run/api.log"
    echo "API failed to start" >&2
    exit 1
  fi
fi

echo "Werewolf lab: http://127.0.0.1:$PORT"
