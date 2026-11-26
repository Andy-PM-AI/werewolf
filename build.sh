#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NODE_BIN="${NODE_BIN:-/Users/xuning/.workbuddy/binaries/node/versions/22.22.2-6/bin}"
if [ -x "$NODE_BIN/node" ]; then
  PATH="$NODE_BIN:$PATH"
  export PATH
fi
if ! command -v node >/dev/null 2>&1; then
  echo "node not found. Set NODE_BIN to a Node 20+ bin directory." >&2
  exit 1
fi
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install --no-audit --no-fund
fi
npm run build
echo "Frontend built: $ROOT/frontend/dist"
