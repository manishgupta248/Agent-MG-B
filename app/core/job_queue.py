"""
Job Queue (Section 4, item 2): SQLite-backed async job tracking.

Scope for this step (M10-S1): schema + enqueue/status/list/cancel CRUD
only. No worker yet - that's M10-S2, built and verified as its own
step once this foundation is confirmed correct.

Design decisions locked in during scoping:
  - READ-only enforcement: enqueue_job refuses any tool whose
    PermissionLevel isn't READ. MODIFY/DELETE/ADMIN tools always run
    synchronously through the normal call_tool approval flow and never
    enter the queue - the async/unattended execution model has no
    mechanism for interactive approval, so allowing a gated tool in
    would either silently bypass approval or require a whole parallel
    approval-deferral system. Simplest, safest boundary.
  - No automatic retries. A failed job is just failed - matches the
    "fail loudly" principle used everywhere else rather than adding
    retry/backoff complexity before it's needed.
  - Worker execution model (M10-S2) will be a bounded ThreadPoolExecutor
    pulling from this table, not asyncio - decided at scoping time,
    noted here for whoever builds that step next.
"""

import json
from typing import Optional

from loguru import logger

from app.core.database import connection
from app.core.event_bus import publish
from app.core.exceptions import DatabaseError, ValidationError
from app.registry.tool_contract import PermissionLevel, get_registry

VALID_JOB_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled"}


def init_job_queue() -> None:
    """
    Creates the jobs table if it doesn't exist. Idempotent, same
    pattern as init_db()/init_knowledge_base(). Called alongside those
    from the main boot sequence.
    """
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | succeeded | failed | cancelled
                result_json TEXT,                        -- nullable; populated by the worker (M10-S2)
                error_message TEXT,                       -- nullable
                run_id TEXT,                              -- nullable; groups jobs the same way call_tool's run_id does
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                started_at TEXT,                          -- nullable; set by the worker
                completed_at TEXT                         -- nullable; set by the worker
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

    logger.info("Job queue initialized - jobs table ready")


def enqueue_job(tool_name: str, input_dict: dict, run_id: Optional[str] = None) -> int:
    """
    Validates tool_name is registered, is READ-permission, and that
    input_dict passes the tool's own input_schema - all BEFORE writing
    a row - then inserts a pending job. Returns the new job's id.

    Raises ValidationError if the tool doesn't exist, isn't READ
    permission, or input_dict fails schema validation. Mirrors
    call_tool's "validate before anything else happens" discipline,
    applied at enqueue time instead of execution time, so a bad job
    never makes it into the table in the first place.
    """
    registry = get_registry()
    registered = registry.get(tool_name)
    if registered is None:
        raise ValidationError(f"Cannot enqueue unknown tool: '{tool_name}' is not registered")

    if registered.permission != PermissionLevel.READ:
        raise ValidationError(
            f"Cannot enqueue '{tool_name}' (permission={registered.permission.value}) - "
            f"only READ-permission tools may be queued. MODIFY/DELETE/ADMIN tools must run "
            f"synchronously through the normal call_tool approval flow."
        )

    try:
        registered.input_schema(**input_dict)
    except Exception as e:
        raise ValidationError(f"Invalid input for '{tool_name}': {e}") from e

    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (tool_name, input_json, status, run_id)
                VALUES (?, ?, 'pending', ?)
                """,
                (tool_name, json.dumps(input_dict, default=str), run_id),
            )
            job_id = cursor.lastrowid
    except DatabaseError:
        logger.error(f"Failed to enqueue job for tool '{tool_name}'")
        raise

    publish("job.enqueued", {"job_id": job_id, "tool_name": tool_name, "run_id": run_id})
    logger.info(f"Enqueued job {job_id} for tool '{tool_name}'")
    return job_id


def get_job(job_id: int) -> Optional[dict]:
    """Fetch a single job by id. Returns None if not found."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def list_jobs(status: Optional[str] = None) -> list[dict]:
    """
    List jobs, optionally filtered by status. No pagination yet - same
    "fine at current scale" reasoning as list_knowledge_items.
    """
    if status is not None and status not in VALID_JOB_STATUSES:
        raise ValidationError(f"Invalid status '{status}' - must be one of {VALID_JOB_STATUSES}")

    with connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()

    return [_row_to_dict(row) for row in rows]


def cancel_job(job_id: int) -> bool:
    """
    Cancels a job, but ONLY if it's still 'pending'. A job that's
    already running, succeeded, failed, or cancelled cannot be
    cancelled again or retroactively stopped - there's no worker/thread
    handle to interrupt yet, and won't be even after M10-S2 without
    real cooperative cancellation, which is out of scope here.

    Returns True if cancelled, False if job_id doesn't exist or isn't
    in a cancellable state.
    """
    existing = get_job(job_id)
    if existing is None:
        return False
    if existing["status"] != "pending":
        return False

    with connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', completed_at = datetime('now') WHERE id = ?",
            (job_id,),
        )

    publish("job.cancelled", {"job_id": job_id, "tool_name": existing["tool_name"]})
    logger.info(f"Cancelled job {job_id}")
    return True


def _row_to_dict(row) -> dict:
    """Converts a sqlite3.Row into a plain dict, deserializing input_json/result_json."""
    return {
        "id": row["id"],
        "tool_name": row["tool_name"],
        "input": json.loads(row["input_json"]),
        "status": row["status"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error_message": row["error_message"],
        "run_id": row["run_id"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }