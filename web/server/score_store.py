"""score_store.py - In-process registry of jobs waiting for the user to accept/retry a self-score.

When the score stage finishes with a sub-threshold result, the pipeline:
  1. Writes score.json
  2. Raises PipelineAwaitingScore(score=...)
  3. The runner catches it, persists the score to the DB, and registers the job HERE
  4. Starts a 60s auto-accept timer thread that signals "accept" if untouched
  5. The runner's main thread blocks on the event

When the user clicks Accept or Try again in the UI, the FastAPI route calls
`resolve_score(job_id, action)` which signals the event with the action.
"""
import logging
import threading
import time
from typing import Dict, Optional

log = logging.getLogger("score_store")

# Tunable: how long to wait for the user before auto-accepting the score
AUTO_ACCEPT_TIMEOUT_SEC = 60.0

# job_id -> {
#   "event":     threading.Event (signals "user resolved or timeout fired"),
#   "score":     dict (the 5-axis score),
#   "action":    "accept" | "retry" | None,
#   "cancelled": bool,
# }
_waiting: Dict[str, dict] = {}
_waiting_lock = threading.Lock()


def register_waiting(job_id: str, score: dict) -> threading.Event:
    """Register a job as waiting for the user to accept/retry the score."""
    event = threading.Event()
    with _waiting_lock:
        _waiting[job_id] = {
            "event": event,
            "score": score,
            "action": None,
            "cancelled": False,
        }

    def auto_accept():
        deadline = time.time() + AUTO_ACCEPT_TIMEOUT_SEC
        while time.time() < deadline:
            if event.wait(timeout=0.5):
                return
            with _waiting_lock:
                if _waiting.get(job_id, {}).get("cancelled"):
                    return
        log.info("score_store: auto-accepting for job %s after %ss",
                 job_id[:8], AUTO_ACCEPT_TIMEOUT_SEC)
        resolve_score(job_id, "accept")

    t = threading.Thread(target=auto_accept, name=f"scoretimer-{job_id[:8]}", daemon=True)
    t.start()
    return event


def resolve_score(job_id: str, action: str) -> bool:
    """action = 'accept' | 'retry'. Returns False if not waiting."""
    if action not in ("accept", "retry"):
        return False
    with _waiting_lock:
        info = _waiting.get(job_id)
        if not info:
            return False
        if info["cancelled"]:
            return False
        info["action"] = action
        info["event"].set()
        return True


def cancel_wait(job_id: str) -> bool:
    with _waiting_lock:
        info = _waiting.get(job_id)
        if not info:
            return False
        info["cancelled"] = True
        info["event"].set()
        return True


def get_waiting_info(job_id: str) -> Optional[dict]:
    with _waiting_lock:
        info = _waiting.get(job_id)
        if not info:
            return None
        return {
            "score": info["score"],
            "action": info["action"],
            "auto_accept_timeout_sec": AUTO_ACCEPT_TIMEOUT_SEC,
        }


def finish_wait(job_id: str) -> Optional[dict]:
    with _waiting_lock:
        info = _waiting.pop(job_id, None)
        if not info:
            return None
        return {"action": info["action"], "cancelled": info["cancelled"]}


def is_waiting(job_id: str) -> bool:
    with _waiting_lock:
        return job_id in _waiting
