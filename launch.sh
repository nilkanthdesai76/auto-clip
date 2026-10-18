#!/usr/bin/env bash
# AutoClip Studio - One-Click Launcher
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

mkdir -p temp

# Check if AutoClip server is already running on port 7860
if lsof -i :7860 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "⚡ AutoClip Studio is already running on http://localhost:7860"
else
  PYTHON_BIN="python3"
  if [ -x ".venv/bin/python3" ]; then
    PYTHON_BIN=".venv/bin/python3"
  fi
  nohup "$PYTHON_BIN" autoclip/web_server.py > temp/server.log 2>&1 &
  SERVER_PID=$!
  echo $SERVER_PID > temp/server.pid

  # Wait up to 5 seconds for server to be responsive
  for i in {1..10}; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:7860 | grep -q "200"; then
      break
    fi
    sleep 0.5
  done
  echo "✅ Server started (PID: $SERVER_PID)"
fi

echo "🌐 Opening AutoClip Studio in your browser..."
open "http://localhost:7860"
