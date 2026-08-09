"""
Workflow Templates execution engine (M12-S2). Resolves a template's
$ref/$param markers against real values, then runs each step through
the existing call_tool() pipeline - approval gating, execution_history
logging, and event publishing all happen exactly as they do for any
other call_tool invocation, because this IS call_tool, just driven by
a saved multi-step plan instead of a single ad-hoc call.

Approval batching: every step in one execute_workflow() call shares
the same run_id. call_tool already implements "same run_id doesn't
re-prompt" via is_run_already_approved()/mark_run_approved() (see
approval.py's module docstring - this is that stub's intended use
case). No new batching logic needed here - just consistent run_id
reuse across steps is sufficient.

Type coercion note: the resolver substitutes real typed values
directly from prior step results - it does NOT attempt its own
coercion. call_tool's existing Pydantic validation is the single
authoritative check for whether a resolved value fits the next tool's
input_schema. Two independent coercion layers could disagree about
what's valid; one authoritative layer is safer.
"""

import json
import uuid
from typing import Optional

from loguru import logger

from app.core.approval import ApprovalHandler
from app.core.call_tool import call_tool
from app.core.database import connection
from app.core.event_bus import publish
from app.core.exceptions import ToolExecutionError, ValidationError
from app.core.workflow_templates import get_workflow_template_by_name


def init_workflow_execution() -> None:
    """Creates workflow_runs and workflow_run_steps if they don't exist. Idempotent."""
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                run_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'running',  -- running | succeeded | failed
                error_message TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_run_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_run_id INTEGER NOT NULL,
                step_number INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                resolved_input_json TEXT NOT NULL,
                status TEXT NOT NULL,   -- succeeded | failed
                result_json TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT,
                FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id)
            )
            """
        )
    logger.info("Workflow execution initialized - workflow_runs/workflow_run_steps tables ready")


def _resolve_path(container, path: list, context: str):
    """
    Walks container following path, branching on segment type: str
    segments index into dicts, int segments index into lists. This is
    the piece missing from M12-S1's validator gap - here it's not just
    validated as acceptable, it's actually used correctly against real
    data, with a clear error the instant a segment doesn't match the
    container it's being applied to.
    """
    current = container
    for segment in path:
        if isinstance(segment, str):
            if not isinstance(current, dict):
                raise ValidationError(
                    f"{context}: path segment '{segment}' expects a dict at this point, "
                    f"got {type(current).__name__}"
                )
            if segment not in current:
                raise ValidationError(
                    f"{context}: key '{segment}' not found (available keys: {list(current.keys())})"
                )
            current = current[segment]
        elif isinstance(segment, int):
            if not isinstance(current, list):
                raise ValidationError(
                    f"{context}: path segment {segment} expects a list at this point, "
                    f"got {type(current).__name__}"
                )
            if segment < 0 or segment >= len(current):
                raise ValidationError(f"{context}: index {segment} out of range (list length {len(current)})")
            current = current[segment]
        else:
            raise ValidationError(f"{context}: invalid path segment {segment!r} (must be str or int)")
    return current


def _resolve_value(value, param_values: dict, step_results: dict[int, dict], step_number: int):
    """
    Recursively resolves $ref/$param markers anywhere in value's
    structure (dicts, lists, nested combinations) into real typed
    values. A $ref/$param dict IS the value once resolved - it's not
    embedded in a string, so the caller gets back whatever type the
    referenced data actually was (list, int, nested dict, etc.).
    """
    if isinstance(value, dict):
        if "$ref" in value:
            ref = value["$ref"]
            ref_step = ref["step"]
            if ref_step not in step_results:
                # Should be unreachable if creation-time validation (M12-S1)
                # did its job - a real occurrence here would mean state
                # drifted between validation and execution somehow.
                raise ValidationError(f"Step {step_number}: $ref points at step {ref_step}, which has no result yet")
            return _resolve_path(step_results[ref_step], ref["path"], f"Step {step_number} $ref->step {ref_step}")

        if "$param" in value:
            param_name = value["$param"]
            if param_name not in param_values:
                raise ValidationError(f"Step {step_number}: $param '{param_name}' was not supplied")
            return param_values[param_name]

        return {k: _resolve_value(v, param_values, step_results, step_number) for k, v in value.items()}

    elif isinstance(value, list):
        return [_resolve_value(v, param_values, step_results, step_number) for v in value]

    return value  # scalar literal


def execute_workflow(
    template_name: str,
    param_values: dict,
    approval_handler: Optional[ApprovalHandler] = None,
) -> dict:
    """
    Executes a saved workflow template by name. Resolves each step's
    input against param_values and prior steps' results, runs it
    through call_tool (approval gating, execution_history logging, and
    event publishing all happen there, unchanged), and stops at the
    first failure - no rollback of already-completed steps.

    Raises ValidationError before any step runs if the template doesn't
    exist or a required parameter is missing - pure usage errors, no
    side effects yet. Once execution starts, failures are captured in
    the returned dict (status='failed') rather than raised, since a
    partially-completed workflow's per-step outcome is valuable
    information the caller needs, not just an exception to catch.

    Returns {"workflow_run_id", "run_id", "status", "steps_completed", "error"}.
    """
    template = get_workflow_template_by_name(template_name)
    if template is None:
        raise ValidationError(f"No workflow template named '{template_name}'")

    for p in template["parameters"]:
        if p.get("required") and p["name"] not in param_values:
            raise ValidationError(f"Missing required parameter '{p['name']}' for workflow '{template_name}'")

    run_id = f"workflow-{template['id']}-{uuid.uuid4().hex[:8]}"

    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO workflow_runs (template_id, run_id, status) VALUES (?, ?, 'running')",
            (template["id"], run_id),
        )
        workflow_run_id = cursor.lastrowid

    publish("workflow.started", {"template_name": template_name, "run_id": run_id})
    logger.info(f"Workflow run {run_id} started (template='{template_name}')")

    step_results: dict[int, dict] = {}

    for i, step in enumerate(template["steps"], start=1):
        tool_name = step["tool_name"]
        raw_input = step.get("input", {})

        try:
            resolved_input = _resolve_value(raw_input, param_values, step_results, i)
        except ValidationError as e:
            return _fail(workflow_run_id, run_id, i, tool_name, raw_input, str(e))

        try:
            result = call_tool(tool_name, resolved_input, run_id=run_id, approval_handler=approval_handler)
        except (ToolExecutionError, ValidationError) as e:
            return _fail(workflow_run_id, run_id, i, tool_name, resolved_input, str(e))

        result_dict = result.model_dump()
        step_results[i] = result_dict
        _record_step(workflow_run_id, i, tool_name, resolved_input, "succeeded", result_dict, None)
        logger.info(f"Workflow run {run_id} step {i} ('{tool_name}') succeeded")

    with connection() as conn:
        conn.execute(
            "UPDATE workflow_runs SET status = 'succeeded', completed_at = datetime('now') WHERE id = ?",
            (workflow_run_id,),
        )
    publish("workflow.succeeded", {"run_id": run_id, "steps": len(template["steps"])})
    logger.info(f"Workflow run {run_id} succeeded ({len(template['steps'])} step(s))")

    return {
        "workflow_run_id": workflow_run_id, "run_id": run_id,
        "status": "succeeded", "steps_completed": len(template["steps"]), "error": None,
    }


def _fail(workflow_run_id: int, run_id: str, step_number: int, tool_name: str, resolved_input, error_message: str) -> dict:
    _record_step(workflow_run_id, step_number, tool_name, resolved_input, "failed", None, error_message)
    with connection() as conn:
        conn.execute(
            "UPDATE workflow_runs SET status = 'failed', error_message = ?, completed_at = datetime('now') WHERE id = ?",
            (error_message, workflow_run_id),
        )
    publish("workflow.failed", {"run_id": run_id, "step": step_number, "error": error_message})
    logger.error(f"Workflow run {run_id} failed at step {step_number} ('{tool_name}'): {error_message}")
    return {
        "workflow_run_id": workflow_run_id, "run_id": run_id,
        "status": "failed", "steps_completed": step_number - 1, "error": error_message,
    }


def _record_step(workflow_run_id, step_number, tool_name, resolved_input, status, result_dict, error_message) -> None:
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO workflow_run_steps
                (workflow_run_id, step_number, tool_name, resolved_input_json, status, result_json, error_message, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                workflow_run_id, step_number, tool_name,
                json.dumps(resolved_input, default=str), status,
                json.dumps(result_dict, default=str) if result_dict else None,
                error_message,
            ),
        )


def get_workflow_run(run_id: str) -> Optional[dict]:
    """Fetch a workflow run's summary by its run_id. Returns None if not found."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"], "template_id": row["template_id"], "run_id": row["run_id"],
        "status": row["status"], "error_message": row["error_message"],
        "started_at": row["started_at"], "completed_at": row["completed_at"],
    }


def list_workflow_run_steps(workflow_run_id: int) -> list[dict]:
    """List all recorded steps for a workflow run, in execution order."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM workflow_run_steps WHERE workflow_run_id = ? ORDER BY step_number ASC",
            (workflow_run_id,),
        ).fetchall()
    return [
        {
            "step_number": r["step_number"], "tool_name": r["tool_name"],
            "resolved_input": json.loads(r["resolved_input_json"]),
            "status": r["status"],
            "result": json.loads(r["result_json"]) if r["result_json"] else None,
            "error_message": r["error_message"],
            "started_at": r["started_at"], "completed_at": r["completed_at"],
        }
        for r in rows
    ]