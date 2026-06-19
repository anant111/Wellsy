"""db.py - SQLite database layer for the AI video pipeline.

Single connection, thread-safe access via a Lock. Schema is created on first import.
"""
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Optional, Tuple

# Resolve paths relative to the project root.
# On Railway (and other deploy targets), override with $DATA_DIR so SQLite +
# per-job media live on the persistent volume instead of /app.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_PROJECT_ROOT, "data"))
DB_PATH = os.path.join(DATA_DIR, "jobs.db")
JOBS_CACHE_DIR = os.path.join(DATA_DIR, "jobs")  # one subfolder per job

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(JOBS_CACHE_DIR, exist_ok=True)

# SQLite + threading: ONE connection guarded by a single lock.
# We use journal_mode=DELETE (not WAL) because WAL has known
# "Data Abort at 0x28" race conditions on macOS when commits
# overlap with reads from the SSE poll loop. DELETE mode is slower
# for concurrent writes but we're already serializing everything
# through the lock, so the perf delta is invisible.
_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA foreign_keys = ON;")
_conn.execute("PRAGMA journal_mode = DELETE;")
_conn.execute("PRAGMA synchronous = NORMAL;")


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    prompt        TEXT NOT NULL,
    duration      INTEGER NOT NULL,
    orientation   TEXT NOT NULL,
    style         TEXT NOT NULL,
    language      TEXT NOT NULL DEFAULT 'en',  -- 'en' | 'hi'
    aspect_mode   TEXT NOT NULL DEFAULT 'single',  -- 'single' | 'both' (v2)
    audio_mode    TEXT NOT NULL DEFAULT 'veo_native',  -- 'veo_native' | 'gemini_tts'
    status        TEXT NOT NULL,        -- queued | running | awaiting_idea | awaiting_score | succeeded | failed | canceled
    current_stage TEXT,                 -- research | scenes | image | clip | compose | score
    current_substage TEXT,              -- NULL | 'ideas' | 'script' | 'self_scoring' | 'awaiting_user'
    error         TEXT,
    created_at    INTEGER NOT NULL,
    started_at    INTEGER,
    finished_at   INTEGER,
    final_path    TEXT,                 -- relative to project root
    chosen_idea_id TEXT,                -- 'idea-1' | 'idea-2' | 'idea-3' | NULL
    score_json    TEXT                  -- JSON blob of {hook, story, momentum, emotional_linkage, closing, total, feedback}
);

CREATE TABLE IF NOT EXISTS job_stages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,          -- research | scenes | image | clip | compose | score
    stage_index INTEGER NOT NULL,       -- 0 for non-repeating stages, 1..N for image/clip/audio
    status      TEXT NOT NULL,          -- pending | running | succeeded | failed | canceled | skipped
    started_at  INTEGER,
    finished_at INTEGER,
    error       TEXT,
    output_path TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_stage ON job_stages(job_id, name, stage_index);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
"""

with _lock:
    _conn.executescript(SCHEMA)
    # Idempotent column adds for older databases
    for stmt in [
        "ALTER TABLE jobs ADD COLUMN current_substage TEXT",
        "ALTER TABLE jobs ADD COLUMN chosen_idea_id TEXT",
        "ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT 'en'",
        "ALTER TABLE jobs ADD COLUMN aspect_mode TEXT NOT NULL DEFAULT 'single'",
        "ALTER TABLE jobs ADD COLUMN audio_mode TEXT NOT NULL DEFAULT 'veo_native'",
        "ALTER TABLE jobs ADD COLUMN score_json TEXT",
    ]:
        try:
            _conn.execute(stmt)
        except sqlite3.OperationalError:
            # column already exists (or NOT NULL DEFAULT on a table with rows —
            # in SQLite that fails differently; we accept both)
            try:
                _conn.execute(f"UPDATE jobs SET {stmt.split('ADD COLUMN')[1].strip().split()[0]} = ? "
                              f"WHERE {stmt.split('ADD COLUMN')[1].strip().split()[0]} IS NULL",
                              ("en" if "language" in stmt else
                               "single" if "aspect_mode" in stmt else
                               "veo_native" if "audio_mode" in stmt else None,))
            except Exception:
                pass
    _conn.commit()


@contextmanager
def _tx():
    """Atomic transaction context."""
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


# ── Public API ─────────────────────────────────────────────────────────

def create_job(prompt: str, duration: int, orientation: str, style: str,
               language: str = "en", aspect_mode: str = "single",
               audio_mode: str = "veo_native") -> str:
    """Create a queued job and return its id."""
    job_id = str(uuid.uuid4())
    now = int(time.time() * 1000)
    with _tx() as c:
        c.execute(
            "INSERT INTO jobs (id, prompt, duration, orientation, style, language, aspect_mode, audio_mode, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
            (job_id, prompt, duration, orientation, style, language, aspect_mode, audio_mode, now),
        )
    # Pre-create the cache dir for this job
    os.makedirs(os.path.join(JOBS_CACHE_DIR, job_id), exist_ok=True)
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        cur = _conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
    return _row_to_job(row) if row else None


def list_jobs(limit: int = 200) -> list:
    with _lock:
        cur = _conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
    return [_row_to_job(r) for r in rows]


def update_job_status(job_id: str, status: str, error: Optional[str] = None,
                      final_path: Optional[str] = None) -> None:
    now = int(time.time() * 1000)
    fields = ["status = ?", "current_stage = ?"]
    params: list = [status, None]  # current_stage cleared on status change
    if status == "running":
        fields.append("started_at = COALESCE(started_at, ?)")
        params.append(now)
    if status in ("succeeded", "failed", "canceled"):
        fields.append("finished_at = ?")
        params.append(now)
    if error is not None:
        fields.append("error = ?")
        params.append(error)
    if final_path is not None:
        fields.append("final_path = ?")
        params.append(final_path)
    params.append(job_id)
    with _tx() as c:
        c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)


def set_substage(job_id: str, substage: Optional[str]) -> None:
    """Set current_substage to one of: NULL, 'ideas', 'script', 'self_scoring'."""
    with _tx() as c:
        c.execute("UPDATE jobs SET current_substage = ? WHERE id = ?", (substage, job_id))


def set_score(job_id: str, score: dict) -> None:
    """Persist the self-score JSON for a job."""
    with _tx() as c:
        c.execute("UPDATE jobs SET score_json = ? WHERE id = ?",
                  (json.dumps(score), job_id))


def set_chosen_idea(job_id: str, idea_id: str) -> None:
    """Persist which idea the user (or the auto-pick) chose."""
    with _tx() as c:
        c.execute("UPDATE jobs SET chosen_idea_id = ? WHERE id = ?", (idea_id, job_id))


def save_ideas(job_id: str, ideas: list) -> str:
    """Write the 3 ideas to <cache_dir>/ideas.json. Returns the path."""
    cache = job_cache_dir(job_id)
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, "ideas.json")
    with open(path, "w") as f:
        json.dump({"ideas": ideas}, f, indent=2)
    return path


def load_ideas(job_id: str) -> Optional[dict]:
    """Read ideas.json for a job, or None if not generated yet."""
    path = os.path.join(job_cache_dir(job_id), "ideas.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_research(job_id: str) -> Optional[dict]:
    """Read research.json for a job, or None if not generated yet."""
    path = os.path.join(job_cache_dir(job_id), "research.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_script(job_id: str) -> Optional[list]:
    """Read scenes.json (the script) for a job, or None if not generated yet."""
    path = os.path.join(job_cache_dir(job_id), "scenes.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def sweep_orphaned_jobs() -> Tuple[int, int]:
    """Mark any jobs left in 'running' or 'queued' as 'canceled' (no handler exists).

    Jobs in 'awaiting_idea' are LEFT ALONE — those are legitimately paused,
    waiting for user input. They become orphaned only if you want a separate
    sweep policy (e.g. timeout > 24h). For now, only the actively running
    states are swept.

    Returns (running_swept, awaiting_idea_left).
    Called once on server startup to clean up after a crash / restart.
    """
    now = int(time.time() * 1000)
    with _tx() as c:
        cur = c.execute(
            "UPDATE jobs SET status = 'canceled', "
            "error = COALESCE(error, 'Server restarted while job was running'), "
            "finished_at = ? "
            "WHERE status IN ('running', 'queued')",
            (now,),
        )
        swept = cur.rowcount
        cur2 = c.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('awaiting_idea', 'awaiting_score')"
        )
        awaiting = cur2.fetchone()["n"]
    return swept, awaiting


def update_job_stage(job_id: str, stage: str) -> None:
    """Just set the current_stage column (used to show what's running)."""
    with _tx() as c:
        c.execute("UPDATE jobs SET current_stage = ? WHERE id = ?", (stage, job_id))


def upsert_stage(job_id: str, name: str, index: int, status: str,
                 output_path: Optional[str] = None, error: Optional[str] = None) -> None:
    now = int(time.time() * 1000)
    with _tx() as c:
        cur = c.execute(
            "SELECT id, started_at FROM job_stages WHERE job_id = ? AND name = ? AND stage_index = ?",
            (job_id, name, index),
        )
        row = cur.fetchone()
        if row is None:
            c.execute(
                "INSERT INTO job_stages (job_id, name, stage_index, status, started_at, finished_at, error, output_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, name, index, status,
                 now if status == "running" else None,
                 now if status in ("succeeded", "failed", "canceled", "skipped") else None,
                 error, output_path),
            )
        else:
            fields = ["status = ?", "error = ?", "output_path = ?"]
            params: list = [status, error, output_path]
            if status == "running" and row[1] is None:
                fields.append("started_at = ?")
                params.append(now)
            if status in ("succeeded", "failed", "canceled", "skipped"):
                fields.append("finished_at = ?")
                params.append(now)
            params.extend([row[0]])
            c.execute(f"UPDATE job_stages SET {', '.join(fields)} WHERE id = ?", params)


def get_stages(job_id: str) -> list:
    with _lock:
        cur = _conn.execute(
            "SELECT name, stage_index, status, started_at, finished_at, error, output_path "
            "FROM job_stages WHERE job_id = ? ORDER BY id",
            (job_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def delete_job(job_id: str) -> None:
    """Delete job row and its media folder."""
    with _tx() as c:
        c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    # Best-effort: remove cache folder
    cache = os.path.join(JOBS_CACHE_DIR, job_id)
    try:
        import shutil
        shutil.rmtree(cache, ignore_errors=True)
    except Exception:
        pass


def job_cache_dir(job_id: str) -> str:
    return os.path.join(JOBS_CACHE_DIR, job_id)


def _row_to_job(row) -> dict:
    return dict(row)
