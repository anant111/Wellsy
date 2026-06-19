"""server.py - FastAPI backend for the AI video pipeline.

Endpoints:
    GET  /api/health
    GET  /api/jobs                  list all jobs
    POST /api/jobs                  create + start a new job
    GET  /api/jobs/{id}             get one job
    DELETE /api/jobs/{id}           delete a job
    POST /api/jobs/{id}/cancel      cancel a running job
    POST /api/jobs/{id}/retry       clone a finished/failed/canceled job and start
    GET  /api/jobs/{id}/stream      SSE for live updates
    GET  /api/media/{job_id}/{path} serve generated images/clips/final.mp4
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

# Make project modules importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from web.server import db
from web.server.sse_broker import broker
import pipeline_runner

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

app = FastAPI(title="AI Video Pipeline", version="0.1.0")

# CORS — local Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────

class CreateJobRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    duration: int = Field(..., description="Total seconds: 15, 30, 60, 120, 240")
    orientation: str = Field(..., pattern=r"^(16:9|9:16)$")
    style: str
    language: str = Field(default="en", pattern=r"^(en|hi)$")
    aspect_mode: str = Field(default="single", pattern=r"^(single|both)$")
    audio_mode: str = Field(default="veo_native", pattern=r"^(veo_native|gemini_tts)$")


class SelectIdeaRequest(BaseModel):
    idea_id: str = Field(..., pattern=r"^idea-[1-3]$")


class ResolveScoreRequest(BaseModel):
    action: str = Field(..., pattern=r"^(accept|retry)$")


# ── Routes ────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    swept, awaiting = db.sweep_orphaned_jobs()
    if swept:
        log.warning("Swept %d orphaned running/queued job(s) from previous server lifetime", swept)
    if awaiting:
        log.warning("Found %d job(s) paused in 'awaiting_idea' — pick an idea in the UI to resume", awaiting)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/jobs")
def list_jobs():
    return db.list_jobs()


@app.post("/api/jobs")
def create_job(req: CreateJobRequest):
    # Validate duration against the allowed set
    from scenes import ALLOWED_DURATIONS
    if req.duration not in ALLOWED_DURATIONS:
        raise HTTPException(400, f"duration must be one of {ALLOWED_DURATIONS}")
    # Validate style
    from image_prompts import ALLOWED_STYLES
    if req.style not in ALLOWED_STYLES:
        raise HTTPException(400, f"style must be one of {ALLOWED_STYLES}")

    job_id = db.create_job(
        req.prompt, req.duration, req.orientation, req.style,
        language=req.language, aspect_mode=req.aspect_mode, audio_mode=req.audio_mode,
    )
    pipeline_runner.start_job(job_id)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job["stages"] = db.get_stages(job_id)
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    if pipeline_runner.is_active(job_id):
        raise HTTPException(409, "Job is running; cancel it first")
    db.delete_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    status = job.get("status")
    if status in ("awaiting_idea", "awaiting_score"):
        # Cancelling a paused job — wake it with cancelled flag
        pipeline_runner.request_cancel_waiting(job_id)
        return {"ok": True}
    if status != "running":
        raise HTTPException(409, f"Job is not running (status: {status})")
    pipeline_runner.request_cancel(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/ideas")
def get_ideas(job_id: str):
    """Return the 3 ideas generated for this job (during awaiting_idea or after)."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    payload = db.load_ideas(job_id)
    if not payload:
        raise HTTPException(404, "Ideas not generated yet")
    # Add the chosen one (if any) for UI highlighting
    job = db.get_job(job_id)
    return {
        "ideas": payload.get("ideas", []),
        "chosen_idea_id": job.get("chosen_idea_id"),
        "auto_pick_timeout_sec": 30,
    }


@app.post("/api/jobs/{job_id}/select-idea")
def select_idea(job_id: str, req: SelectIdeaRequest):
    """Resume the paused job with the user's chosen idea."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    ok = pipeline_runner.resume_job(job_id, req.idea_id)
    if not ok:
        raise HTTPException(409, "Job is not waiting for an idea choice")
    return {"ok": True, "idea_id": req.idea_id}


@app.get("/api/jobs/{job_id}/research-brief")
def get_research_brief(job_id: str):
    """Return the research.json content for a job (or 404 if not generated yet)."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    brief = db.load_research(job_id)
    if not brief:
        raise HTTPException(404, "Research brief not generated yet")
    return brief


@app.get("/api/jobs/{job_id}/script")
def get_script(job_id: str):
    """Return the scenes.json content (the scene script) for a job."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    script = db.load_script(job_id)
    if not script:
        raise HTTPException(404, "Scene script not generated yet")
    # Attach the chosen idea for context
    job = db.get_job(job_id)
    ideas_payload = db.load_ideas(job_id)
    chosen = None
    if job.get("chosen_idea_id") and ideas_payload:
        chosen = next(
            (i for i in ideas_payload.get("ideas", []) if i["id"] == job["chosen_idea_id"]),
            None,
        )
    return {"scenes": script, "chosen_idea": chosen}


@app.get("/api/jobs/{job_id}/score")
def get_score(job_id: str):
    """Return the self-score JSON for a job (wrapped in {score, threshold, auto_accept_seconds}).

    The response shape matches the SSE `score` event the runner publishes, so
    both `AwaitingScoreSection` and `ScoreBreakdownLoader` can use the same
    parsing code.
    """
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    raw = job.get("score_json")
    if not raw:
        raise HTTPException(404, "No score yet for this job")
    try:
        score = json.loads(raw)
    except Exception:
        return {"raw": raw, "threshold": 7, "auto_accept_seconds": 60}
    if not isinstance(score, dict) or "total" not in score:
        return {"raw": raw, "threshold": 7, "auto_accept_seconds": 60}
    return {
        "score": score,
        "threshold": 7,
        "auto_accept_seconds": 60,
    }


@app.post("/api/jobs/{job_id}/resolve-score")
def resolve_score(job_id: str, req: ResolveScoreRequest):
    """Resume the paused job after the user accepts or retries the self-score."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    ok = pipeline_runner.resolve_score_job(job_id, req.action)
    if not ok:
        raise HTTPException(409, "Job is not waiting for a score accept/retry")
    return {"ok": True, "action": req.action}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    try:
        new_id = pipeline_runner.retry_job(job_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"id": new_id}


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    """Server-Sent Events for live job updates."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")

    async def event_gen():
        q = await broker.subscribe(job_id)
        try:
            # Initial snapshot
            job = db.get_job(job_id)
            if job:
                yield f"data: {json.dumps({'type': 'snapshot', 'job': job, 'stages': db.get_stages(job_id)})}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # heartbeat
                    yield ":keepalive\n\n"
                    continue
                if msg is None:
                    break
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            await broker.unsubscribe(job_id, q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/media/{job_id}/{path:path}")
def serve_media(job_id: str, path: str):
    """Serve images, clips, or final.mp4 for a job. Path is relative to the job's cache dir."""
    if not db.get_job(job_id):
        raise HTTPException(404, "Job not found")
    # Resolve safely inside the job's cache folder
    cache = Path(db.job_cache_dir(job_id)).resolve()
    requested = (cache / path).resolve()
    try:
        requested.relative_to(cache)
    except ValueError:
        raise HTTPException(403, "Path escapes job directory")
    if not requested.exists() or not requested.is_file():
        raise HTTPException(404, f"File not found: {path}")
    return FileResponse(str(requested))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)
