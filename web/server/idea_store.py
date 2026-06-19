"""idea_store.py - In-process registry of jobs waiting for the user to pick an idea.

When a job hits the 'scenes' stage, the pipeline:
  1. Generates 3 ideas
  2. Raises PipelineAwaitingIdea(ideas=...)
  3. The runner catches it, saves ideas.json, and registers the job HERE
  4. Starts a 30s timer thread that, if uninterrupted, sets the selection
     to 'idea-1' and signals the event
  5. The runner's main thread blocks on the event

When the user clicks an idea card in the UI, the FastAPI route calls
`select_idea(job_id, idea_id)` which signals the event with the chosen id.
The runner wakes, persists the choice to the DB, flips status back to
'running', and continues the pipeline.

On server restart, in-memory state is gone — jobs in 'awaiting_idea' remain
paused in the DB. The user can resume by picking an idea (which re-enters
this flow) or by retrying the job from scratch.
"""
import logging
import threading
import time
from typing import Dict, Optional

log = logging.getLogger("idea_store")

# Tunable: how long to wait for the user before auto-picking the first idea
AUTO_PICK_TIMEOUT_SEC = 30.0

# job_id -> {
#   "event":     threading.Event (signals "user picked or timeout fired"),
#   "ideas":     list of 3 idea dicts,
#   "selected":  str | None (set by the timer thread or the HTTP handler),
#   "cancelled": bool (set when the user clicked Cancel during the wait),
# }
_waiting: Dict[str, dict] = {}
_waiting_lock = threading.Lock()


def register_waiting(job_id: str, ideas: list) -> threading.Event:
    """Register a job as waiting for an idea. Returns the event to wait on.

    Starts a background timer thread that auto-picks idea-1 after the timeout.
    """
    event = threading.Event()
    with _waiting_lock:
        _waiting[job_id] = {
            "event": event,
            "ideas": ideas,
            "selected": None,
            "cancelled": False,
        }

    def auto_pick():
        # Sleep, but check cancelled periodically
        deadline = time.time() + AUTO_PICK_TIMEOUT_SEC
        while time.time() < deadline:
            if event.wait(timeout=0.5):
                # Someone already picked — exit cleanly
                return
            with _waiting_lock:
                if _waiting.get(job_id, {}).get("cancelled"):
                    return
        # Timeout — auto-pick idea-1
        log.info("idea_store: auto-picking idea-1 for job %s after %ss",
                 job_id[:8], AUTO_PICK_TIMEOUT_SEC)
        select_idea(job_id, "idea-1")

    t = threading.Thread(target=auto_pick, name=f"ideatimer-{job_id[:8]}", daemon=True)
    t.start()
    return event


def select_idea(job_id: str, idea_id: str) -> bool:
    """Set the selection and wake the waiting thread. Returns False if not waiting."""
    with _waiting_lock:
        info = _waiting.get(job_id)
        if not info:
            return False
        if info["cancelled"]:
            return False
        # Validate
        valid = {i["id"] for i in info["ideas"]}
        if idea_id not in valid:
            log.warning("select_idea: invalid id %s for job %s", idea_id, job_id[:8])
            return False
        info["selected"] = idea_id
        info["event"].set()
        return True


def cancel_wait(job_id: str) -> bool:
    """Mark a waiting job as cancelled and wake its thread (which exits cleanly)."""
    with _waiting_lock:
        info = _waiting.get(job_id)
        if not info:
            return False
        info["cancelled"] = True
        info["event"].set()
        return True


def get_waiting_info(job_id: str) -> Optional[dict]:
    """Snapshot of the wait state for a job, or None if not waiting."""
    with _waiting_lock:
        info = _waiting.get(job_id)
        if not info:
            return None
        return {
            "ideas": info["ideas"],
            "selected": info["selected"],
            "cancelled": info["cancelled"],
            "auto_pick_timeout_sec": AUTO_PICK_TIMEOUT_SEC,
        }


def finish_wait(job_id: str) -> Optional[dict]:
    """Remove a job from the wait registry. Returns the final selected id, or None."""
    with _waiting_lock:
        info = _waiting.pop(job_id, None)
        if not info:
            return None
        return {
            "selected": info["selected"],
            "cancelled": info["cancelled"],
        }


def is_waiting(job_id: str) -> bool:
    with _waiting_lock:
        return job_id in _waiting
