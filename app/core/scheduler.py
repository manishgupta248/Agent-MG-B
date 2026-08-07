"""
Scheduler (Section 4, item 3): time/interval-based triggering of
scheduled tool calls, separate from the Job Queue (M10) - the
Scheduler decides WHEN something should run; the Job Queue's existing
worker decides WHEN it actually executes and by what (M11-S2 will have
a firing task enqueue a Job Queue job rather than calling call_tool
directly).

Scope for this step (M11-S1): schema + CRUD only, plus get_due_tasks()/
mark_task_fired() for the trigger loop to call next step. No polling
loop yet.

Design decisions locked in during scoping:
  - Two schedule types: 'interval' (run every N seconds, repeating
    indefinitely until disabled/deleted) and 'one_time' (run once at a
    specific datetime, then auto-disables). Full cron expressions
    deferred to a later step.
  - READ-only enforcement, same reasoning as the Job Queue (M10-S1):
    create_scheduled_task refuses any tool whose PermissionLevel isn't
    READ, since the unattended execution model has no mechanism for
    interactive approval.
  - Missed runs while offline are SKIPPED, not caught up - see
    mark_task_fired()'s docstring for the concrete mechanism.
  - All datetimes stored/compared in UTC, matching SQLite's
    datetime('now') (UTC by default), so next_run_at <= datetime('now')
    works as a plain SQL WHERE clause. one_time tasks accept a
    caller-supplied timezone (default Asia/Kolkata, same pattern as
    the Calendar tools from M9-S4) and convert to UTC at creation.
"""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo

from loguru import logger

from app.core.database import connection
from app.core.exceptions import DatabaseError, ValidationError
from app.registry.tool_contract import PermissionLevel, get_registry

VALID_SCHEDULE_TYPES = {"interval", "one_time"}
DEFAULT_TIMEZONE = "Asia/Kolkata"

# SQLite datetime('now') format - kept consistent everywhere here so
# next_run_at compares correctly against it in plain SQL.
_SQLITE_DT_FORMAT = "%Y-%m-%d %H:%M:%S"


def _utc_now_str() -> str:
    return datetime.now(dt_timezone.utc).strftime(_SQLITE_DT_FORMAT)


def init_scheduler() -> None:
    """Creates the scheduled_tasks table if it doesn't exist. Idempotent."""
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                schedule_type TEXT NOT NULL,       -- interval | one_time
                interval_seconds INTEGER,           -- required if schedule_type='interval'
                run_at TEXT,                        -- informational UTC copy, one_time only
                next_run_at TEXT NOT NULL,          -- UTC, drives due-check comparisons
                last_run_at TEXT,                   -- nullable, UTC
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due ON scheduled_tasks(enabled, next_run_at)"
        )

    logger.info("Scheduler initialized - scheduled_tasks table ready")


def create_scheduled_task(
    tool_name: str,
    input_dict: dict,
    schedule_type: str,
    interval_seconds: Optional[int] = None,
    run_at: Optional[str] = None,
    run_at_timezone: str = DEFAULT_TIMEZONE,
) -> int:
    """
    Validates tool_name is registered, is READ-permission, and that
    input_dict passes the tool's own input_schema - same enforcement,
    same reasoning as Job Queue's enqueue_job (M10-S1).

    interval: interval_seconds required, positive. First run is
    scheduled interval_seconds from now - a newly created recurring
    task doesn't fire immediately on creation.

    one_time: run_at required (naive ISO 8601, e.g. '2026-08-10T15:00:00'),
    interpreted in run_at_timezone, converted to UTC for storage. Must
    be in the future at creation time - a past run_at is almost
    certainly a mistake, not a "run immediately" request, so this
    raises rather than silently firing on the next poll.

    Returns the new task's id.
    """
    registry = get_registry()
    registered = registry.get(tool_name)
    if registered is None:
        raise ValidationError(f"Cannot schedule unknown tool: '{tool_name}' is not registered")

    if registered.permission != PermissionLevel.READ:
        raise ValidationError(
            f"Cannot schedule '{tool_name}' (permission={registered.permission.value}) - "
            f"only READ-permission tools may be scheduled. MODIFY/DELETE/ADMIN tools must run "
            f"synchronously through the normal call_tool approval flow."
        )

    try:
        registered.input_schema(**input_dict)
    except Exception as e:
        raise ValidationError(f"Invalid input for '{tool_name}': {e}") from e

    if schedule_type not in VALID_SCHEDULE_TYPES:
        raise ValidationError(f"Invalid schedule_type '{schedule_type}' - must be one of {VALID_SCHEDULE_TYPES}")

    stored_run_at = None

    if schedule_type == "interval":
        if not interval_seconds or interval_seconds <= 0:
            raise ValidationError("interval_seconds must be a positive integer for schedule_type='interval'")
        next_run_dt = datetime.now(dt_timezone.utc) + timedelta(seconds=interval_seconds)
    else:  # one_time
        if not run_at:
            raise ValidationError("run_at is required for schedule_type='one_time'")
        try:
            naive = datetime.fromisoformat(run_at)
        except ValueError as e:
            raise ValidationError(f"Expected ISO 8601 datetime for run_at, got '{run_at}': {e}") from e
        try:
            tz = ZoneInfo(run_at_timezone)
        except Exception as e:
            raise ValidationError(f"Invalid timezone '{run_at_timezone}': {e}") from e

        localized = naive.replace(tzinfo=tz)
        next_run_dt = localized.astimezone(dt_timezone.utc)

        if next_run_dt <= datetime.now(dt_timezone.utc):
            raise ValidationError(
                f"run_at '{run_at}' ({run_at_timezone}) is in the past - one_time tasks must be scheduled "
                f"in the future. Missed schedules are not caught up retroactively (see module docstring)."
            )
        stored_run_at = next_run_dt.strftime(_SQLITE_DT_FORMAT)

    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO scheduled_tasks
                    (tool_name, input_json, schedule_type, interval_seconds, run_at, next_run_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    json.dumps(input_dict, default=str),
                    schedule_type,
                    interval_seconds if schedule_type == "interval" else None,
                    stored_run_at,
                    next_run_dt.strftime(_SQLITE_DT_FORMAT),
                ),
            )
            task_id = cursor.lastrowid
    except DatabaseError:
        logger.error(f"Failed to create scheduled task for tool '{tool_name}'")
        raise

    logger.info(f"Created scheduled task {task_id} ({schedule_type}) for tool '{tool_name}'")
    return task_id


def get_scheduled_task(task_id: int) -> Optional[dict]:
    """Fetch a single scheduled task by id. Returns None if not found."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def list_scheduled_tasks(enabled_only: bool = False) -> list[dict]:
    """List scheduled tasks, optionally filtered to enabled=1 only."""
    with connection() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY next_run_at ASC"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY next_run_at ASC").fetchall()
    return [_row_to_dict(row) for row in rows]


def set_task_enabled(task_id: int, enabled: bool) -> bool:
    """Enables/disables a task without deleting it. Returns True if updated, False if not found."""
    existing = get_scheduled_task(task_id)
    if existing is None:
        return False

    with connection() as conn:
        conn.execute("UPDATE scheduled_tasks SET enabled = ? WHERE id = ?", (1 if enabled else 0, task_id))
    return True


def delete_scheduled_task(task_id: int) -> bool:
    """Delete a scheduled task. Returns True if a row was deleted, False if not found."""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0


def get_due_tasks() -> list[dict]:
    """
    Returns all enabled tasks whose next_run_at has passed (<= now,
    UTC). Called by the trigger loop (M11-S2).
    """
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE enabled = 1 AND next_run_at <= datetime('now') ORDER BY next_run_at ASC"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_task_fired(task_id: int) -> None:
    """
    Called by the trigger loop (M11-S2) after successfully enqueuing a
    due task's job. Behavior depends on schedule_type:
      - interval: advances next_run_at by interval_seconds from NOW
        (not from the previous next_run_at) - so a task that sat due
        while the agent was offline doesn't fire a burst of catch-up
        occurrences once noticed; it resumes at a normal interval from
        whenever it was actually seen. This IS the "skip missed runs"
        decision, implemented concretely.
      - one_time: disables itself (enabled=0) - done its one job, not
        due again.
    """
    task = get_scheduled_task(task_id)
    if task is None:
        return

    now_str = _utc_now_str()

    if task["schedule_type"] == "interval":
        next_run_dt = datetime.now(dt_timezone.utc) + timedelta(seconds=task["interval_seconds"])
        with connection() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (now_str, next_run_dt.strftime(_SQLITE_DT_FORMAT), task_id),
            )
    else:  # one_time
        with connection() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET last_run_at = ?, enabled = 0 WHERE id = ?",
                (now_str, task_id),
            )


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "tool_name": row["tool_name"],
        "input": json.loads(row["input_json"]),
        "schedule_type": row["schedule_type"],
        "interval_seconds": row["interval_seconds"],
        "run_at": row["run_at"],
        "next_run_at": row["next_run_at"],
        "last_run_at": row["last_run_at"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
    }