#!/usr/bin/env bash
# AutoClip Studio - Stop Server
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "🛑 Stopping AutoClip Studio..."

if [ -f temp/server.pid ]; then
  PID=$(cat temp/server.pid)
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    echo "✅ Stopped AutoClip server process (PID $PID)"
  fi
  rm -f temp/server.pid
fi

# Also kill any remaining process bound to port 7860
PIDS=$(lsof -ti :7860 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  kill -9 $PIDS 2>/dev/null || true
  echo "✅ Freed port 7860"
fi

echo "✨ AutoClip Studio stopped cleanly."
