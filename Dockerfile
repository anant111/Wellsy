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

# Use exec form (no /bin/sh -c wrapping) and call uvicorn directly. The
# exec form lets Railway's container runtime exec the binary cleanly.
# PORT is injected by Railway; defaults to 8080.
WORKDIR /app/ai_video_pipeline/web/server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]