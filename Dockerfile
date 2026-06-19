# Railway Dockerfile for the AI Video Pipeline backend.
#
# Railway auto-detects Python and uses this file. We need:
#   1. ffmpeg installed (for video concat + audio mux)
#   2. The Python deps from web/server/requirements.txt
#   3. The whole ai_video_pipeline/ tree (so pipeline_lib, generator, etc. are importable)
#
# Build context is the repo root (/app on Railway). We copy ai_video_pipeline/
# into /app/ai_video_pipeline/ and run uvicorn from /app/ai_video_pipeline/web/server.
FROM python:3.11-slim

# System deps: ffmpeg for video/audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better Docker layer caching)
COPY web/server/requirements.txt /app/web/server/requirements.txt
RUN pip install --no-cache-dir -r /app/web/server/requirements.txt

# Copy the whole project (skill markdown, scenes.py, etc.)
COPY . /app/ai_video_pipeline/

# Make /app/ai_video_pipeline/ importable so pipeline_lib / generator / etc. resolve
ENV PYTHONPATH=/app/ai_video_pipeline:/app/ai_video_pipeline/web/server
ENV PYTHONUNBUFFERED=1

# Persistent volume for SQLite + per-job media is mounted by Railway at the
# service level (UI > Settings > Volumes > Mount Path: /data). Railway's
# builder rejects VOLUME directives in Dockerfiles, so we just create the
# directory inside the image so the mount has a target.
RUN mkdir -p /data

# Use a small /bin/sh entrypoint so we can:
#   - handle $PORT (Railway injects it; exec form doesn't expand env vars)
#   - exec uvicorn as PID 1 so SIGTERM (Railway shutdown) reaches the app
# The CMD below uses exec form pointing at the entrypoint script.
WORKDIR /app/ai_video_pipeline/web/server
CMD ["/bin/sh", "/app/ai_video_pipeline/web/server/start.sh"]