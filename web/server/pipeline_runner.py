"""pipeline_runner.py - Spawn and manage pipeline jobs in background threads.

Each job runs in its own thread with its own cancel event. The 'scenes'
stage can pause (awaiting_idea) while the user picks an idea, then resume.
The 'score' stage can pause (awaiting_score) while the user accepts or
retries the self-score, then resume.
"""
import logging
import os
import sys
import threading
from typing import Dict

# Make the ai_video_pipeline package importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from web.server import db
from web.server.sse_broker import broker
from web.server import idea_store
from web.server import score_store
from pipeline_lib import (
    run_pipeline, PipelineCanceled, PipelineAwaitingIdea, PipelineAwaitingScore,
)

log = logging.getLogger("pipeline_runner")

# Active jobs: job_id -> { thread, cancel_event }
_active: Dict[str, dict] = {}
_active_lock = threading.Lock()


def is_active(job_id: str) -> bool:
    with _active_lock:
        return job_id in _active


def request_cancel(job_id: str) -> bool:
    """Signal a running job to stop. Returns False if not running."""
    with _active_lock:
        info = _active.get(job_id)
        if not info:
            return False
        info["cancel_event"].set()
        return True


def request_cancel_waiting(job_id: str) -> bool:
    """Cancel a job that is paused awaiting an idea or score choice."""
    idea_store.cancel_wait(job_id)
    score_store.cancel_wait(job_id)
    request_cancel(job_id)  # also signal the thread's event
    return True


def _make_emit(job_id: str):
    """Build the emit callback used by pipeline_lib."""
    def emit(stage: str, status: str, index: int, output_path, error):
        try:
            db.upsert_stage(job_id, stage, index, status, output_path=output_path, error=error)
            if status == "running":
                db.update_job_stage(job_id, stage)
                if stage == "scenes":
                    # The first time scenes starts, mark the substage as "ideas".
                    # When run_pipeline is re-entered with a chosen idea, it'll
                    # call emit("scenes", "running") again — but in that case
                    # we've already moved on to the "script" substage in
                    # self_loop, so don't overwrite it back to "ideas".
                    cur = db.get_job(job_id)
                    if cur and cur.get("chosen_idea_id") is None:
                        db.set_substage(job_id, "ideas")
        except Exception as e:
            log.exception("db.upsert_stage failed: %s", e)
        try:
            broker.publish(job_id, {
                "type": "stage",
                "stage": stage,
                "index": index,
                "status": status,
                "output_path": output_path,
                "error": error,
            })
        except Exception as e:
            log.exception("broker.publish failed: %s", e)
    return emit


def start_job(job_id: str) -> None:
    """Spawn a thread that runs the pipeline for this job."""
    job = db.get_job(job_id)
    if not job:
        raise ValueError(f"No such job: {job_id}")

    cancel_event = threading.Event()

    def runner():
        db.update_job_status(job_id, "running")
        emit = _make_emit(job_id)
        try:
            self_loop(job_id, job, cache_dir=db.job_cache_dir(job_id),
                      emit=emit, cancel_event=cancel_event)
        except PipelineCanceled:
            db.update_job_status(job_id, "canceled")
            broker.publish(job_id, {"type": "job", "status": "canceled"})
        except Exception as e:
            log.exception("Job %s failed", job_id)
            db.update_job_status(job_id, "failed", error=str(e))
            broker.publish(job_id, {"type": "job", "status": "failed", "error": str(e)})
        finally:
            broker.close(job_id)
            with _active_lock:
                _active.pop(job_id, None)

    thread = threading.Thread(target=runner, name=f"job-{job_id[:8]}", daemon=True)
    with _active_lock:
        _active[job_id] = {"thread": thread, "cancel_event": cancel_event}
    thread.start()


def self_loop(job_id, job, cache_dir, emit, cancel_event):
    """The pipeline driver. Runs stages 1→2a, then waits for an idea,
    then runs 2b→3→4→5→6→7. Handles re-entry on the same thread so the
    wait happens in this thread (not a callback)."""
    chosen_idea = None
    skip_score = False
    while True:
        try:
            final = run_pipeline(
                job_id=job_id,
                prompt=job["prompt"],
                duration=job["duration"],
                orientation=job["orientation"],
                style=job["style"],
                cache_dir=cache_dir,
                emit=emit,
                cancel_event=cancel_event,
                chosen_idea=chosen_idea,
                language=job.get("language") or "en",
                audio_mode=job.get("audio_mode") or "veo_native",
                skip_score=skip_score,
            )
            # Pipeline complete
            rel_final = os.path.relpath(final, PROJECT_ROOT)
            db.update_job_status(job_id, "succeeded", final_path=rel_final)
            broker.publish(job_id, {
                "type": "job",
                "status": "succeeded",
                "final_path": rel_final,
            })
            return
        except PipelineAwaitingIdea as e:
            # Save the ideas, flip status, start the timer, and wait
            db.save_ideas(job_id, e.ideas)
            db.set_substage(job_id, "ideas")
            db.update_job_status(job_id, "awaiting_idea")
            broker.publish(job_id, {
                "type": "ideas",
                "ideas": e.ideas,
                "auto_pick_seconds": idea_store.AUTO_PICK_TIMEOUT_SEC,
            })
            log.info("Job %s awaiting idea choice (%d ideas)", job_id[:8], len(e.ideas))

            # Register the wait — this also starts the 30s auto-pick timer
            event = idea_store.register_waiting(job_id, e.ideas)
            event.wait()  # blocks here

            # Woken up: extract the final state
            result = idea_store.finish_wait(job_id)
            if not result or result.get("cancelled"):
                raise PipelineCanceled()
            chosen_idea_id = result.get("selected") or "idea-1"
            chosen_idea = next((i for i in e.ideas if i["id"] == chosen_idea_id), e.ideas[0])

            db.set_chosen_idea(job_id, chosen_idea["id"])
            db.set_substage(job_id, "script")
            db.update_job_status(job_id, "running")
            broker.publish(job_id, {
                "type": "job",
                "status": "running",
                "chosen_idea_id": chosen_idea["id"],
            })
            log.info("Job %s resuming with idea %s", job_id[:8], chosen_idea["id"])
            # Loop again — run_pipeline will see chosen_idea != None and skip 2a
            continue

        except PipelineAwaitingScore as e:
            db.set_score(job_id, e.score)
            db.set_substage(job_id, "awaiting_user")
            db.update_job_status(job_id, "awaiting_score")
            broker.publish(job_id, {
                "type": "score",
                "score": e.score,
                "threshold": e.threshold,
                "auto_accept_seconds": score_store.AUTO_ACCEPT_TIMEOUT_SEC,
            })
            log.info("Job %s awaiting score accept/retry (total=%d)",
                     job_id[:8], e.score.get("total", 0))

            event = score_store.register_waiting(job_id, e.score)
            event.wait()

            result = score_store.finish_wait(job_id)
            if not result or result.get("cancelled"):
                raise PipelineCanceled()
            action = result.get("action") or "accept"
            db.update_job_status(job_id, "running")
            broker.publish(job_id, {
                "type": "job",
                "status": "running",
                "score_action": action,
            })
            if action == "accept":
                skip_score = True
                log.info("Job %s user accepted score", job_id[:8])
            else:
                # retry: clear score.json, regenerate
                score_path = os.path.join(cache_dir, "score.json")
                if os.path.exists(score_path):
                    os.remove(score_path)
                skip_score = False
                log.info("Job %s user requested retry (full regen)", job_id[:8])
            continue


def resume_job(job_id: str, idea_id: str) -> bool:
    """Called by the HTTP handler when the user picks an idea."""
    return idea_store.select_idea(job_id, idea_id)


def resolve_score_job(job_id: str, action: str) -> bool:
    """Called by the HTTP handler when the user accepts/retries the score."""
    return score_store.resolve_score(job_id, action)


def retry_job(job_id: str) -> str:
    """Clone a job's parameters into a new queued job and start it."""
    src = db.get_job(job_id)
    if not src:
        raise ValueError(f"No such job: {job_id}")
    if src["status"] == "running":
        raise ValueError("Job is still running; cancel it first")
    if src["status"] == "awaiting_idea":
        raise ValueError("Job is awaiting an idea choice; pick one or cancel first")
    if src["status"] == "awaiting_score":
        raise ValueError("Job is awaiting a score accept/retry; resolve it first")
    new_id = db.create_job(
        prompt=src["prompt"],
        duration=src["duration"],
        orientation=src["orientation"],
        style=src["style"],
        language=src.get("language") or "en",
        aspect_mode=src.get("aspect_mode") or "single",
        audio_mode=src.get("audio_mode") or "veo_native",
    )
    start_job(new_id)
    return new_id
