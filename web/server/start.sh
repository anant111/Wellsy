#!/bin/sh
# Entrypoint for Railway. WORKDIR is already /app/ai_video_pipeline/web/server
# (set in Dockerfile), so no cd needed. exec replaces the shell with
# uvicorn so SIGTERM from Railway's shutdown reaches the app.
set -e
export PORT="${PORT:-8080}"
exec uvicorn server:app --host 0.0.0.0 --port "$PORT"