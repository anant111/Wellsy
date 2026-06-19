#!/bin/bash
# start.sh - launch the AI Video Pipeline (Python backend + Next.js frontend).
# Usage: ./start.sh
set -e

# Always resolve paths relative to this script, no matter who calls it
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PIPELINE_DIR="$SCRIPT_DIR"
SERVER_DIR="$SCRIPT_DIR/web/server"
WEB_DIR="$SCRIPT_DIR/web"

VENV="$PROJECT_ROOT/venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

if [ ! -x "$PY" ]; then
  echo "❌ Python venv not found at $VENV"
  echo "   Create it: python3 -m venv $VENV && $PIP install -r $SERVER_DIR/requirements.txt"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "❌ ffmpeg is not installed. Install with: brew install ffmpeg"
  exit 1
fi

echo "🧹 Starting Python backend on :8765…"
(
  cd "$SERVER_DIR"
  "$PY" -m uvicorn server:app --port 8765 --log-level info
) > /tmp/ai_video_pipeline_backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to be healthy
for i in {1..20}; do
  if curl -sf http://127.0.0.1:8765/api/health > /dev/null 2>&1; then
    echo "✅ Backend is up (PID $BACKEND_PID)"
    break
  fi
  sleep 1
done
if ! curl -sf http://127.0.0.1:8765/api/health > /dev/null 2>&1; then
  echo "❌ Backend failed to start. Last log:"
  tail -30 /tmp/ai_video_pipeline_backend.log
  kill $BACKEND_PID 2>/dev/null
  exit 1
fi

echo "🌐 Starting Next.js frontend on :3000…"
(
  cd "$WEB_DIR"
  if [ ! -d node_modules ]; then
    echo "📦 Installing npm dependencies (first run)…"
    npm install
  fi
  npm run dev
) > /tmp/ai_video_pipeline_frontend.log 2>&1 &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "🛑 Stopping…"
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  AI Video Pipeline"
echo "  Backend:  http://localhost:8765/api/health"
echo "  Frontend: http://localhost:3000"
echo "  Logs:     /tmp/ai_video_pipeline_backend.log"
echo "            /tmp/ai_video_pipeline_frontend.log"
echo "  Press Ctrl+C to stop."
echo "════════════════════════════════════════════════════════════"
echo ""

# Block until either child dies (use plain `wait` on older bash)
while kill -0 $BACKEND_PID 2>/dev/null && kill -0 $FRONTEND_PID 2>/dev/null; do
  sleep 1
done
echo "One of the servers exited; shutting down…"
exit 1
