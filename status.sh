#!/bin/sh
set -eu
PORT="${WEREWOLF_PORT:-8791}"
curl -sS "http://127.0.0.1:$PORT/api/health" || {
  echo ""
  echo "API is not responding on port $PORT" >&2
  exit 1
}
echo ""
