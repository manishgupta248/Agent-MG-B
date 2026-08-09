"""
Workflow Templates (Section 4, item 8): named, parameterized,
multi-step automations. Sits between Tier1.5 compound pipelines and
Tier4 LangGraph dynamic planning in the intent-resolution stack - a
template is a SAVED, reusable version of a multi-step plan, invoked by
name with caller-supplied parameters, as opposed to Tier4's ad-hoc
per-request planning.

Scope for this step (M12-S1): schema + CRUD + creation-time validation
only. No execution engine yet - that's M12-S2.

Design decisions (see chat for full reasoning):
  - Steps may call tools of ANY permission level (READ/MODIFY/DELETE/
    ADMIN) - unlike Job Queue/Scheduler's READ-only restriction. A
    workflow is invoked interactively by a human in the moment, not
    fired unattended in the background, so the execution engine (M12-S2)
    will route each step through call_tool with a real approval_handler
    and let approval gating work exactly as it does for any other
    synchronous call.
  - Step-chaining uses STRUCTURED references, not string placeholders:
    {"$ref": {"step": N, "path": ["output", "file_id"]}} pulls a value
    out of an earlier step's stored result; {"$param": "param_name"}
    pulls a value from caller-supplied invocation parameters. Chosen
    over string templates specifically because a structured reference
    IS the input value - resolution substitutes the actual typed value
    directly, with no string-embedding/stringification step to get
    wrong. Ties directly to the logged lesson "deterministic type
    coercion required between chained tool outputs/inputs."
  - Storage is dynamic (SQLite), matching Job Queue/Scheduler/Knowledge
    Base, keeping the door open for a future step where a successful
    ad-hoc Tier4 plan gets saved as a reusable template at runtime.
  - Reference validation happens at CREATION time: every $ref must
    point at an earlier step number that exists in this template,
    every $param must name a declared parameter. This is the "fail
    loudly on unresolved refs" lesson applied as early as possible - a
    template with a dangling reference should never be creatable,
    rather than failing confusingly the first time someone runs it.
  - Full Pydantic input_schema validation is deliberately NOT done at
    creation time - a step's input isn't fully known until $ref/$param
    placeholders are resolved at execution time (M12-S2), which itself
    runs the resolved input through call_tool's own validation anyway.
    This step only validates what CAN be known now: tool existence and
    reference integrity.
"""

import json
from typing import Optional

from loguru import logger

from app.core.database import connection
from app.core.exceptions import DatabaseError, ValidationError
from app.registry.tool_contract import get_registry


def init_workflow_templates() -> None:
    """Creates the workflow_templates table if it doesn't exist. Idempotent."""
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                parameters_json TEXT NOT NULL,   -- list of {name, description, required}
                steps_json TEXT NOT NULL,         -- ordered list of {tool_name, input}
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
    logger.info("Workflow templates initialized - workflow_templates table ready")


def _validate_references(value, step_count: int, declared_param_names: set, step_number: int) -> None:
    """
    Recursively walks a step's input (dicts/lists/scalars) looking for
    $ref and $param markers, validating each at CREATION time rather
    than deferring to execution. Covers nested dict/list paths per the
    logged lesson - a $ref buried inside a list of dicts is checked
    exactly the same as a top-level one.

    Raises ValidationError with a specific, locatable message on the
    first bad reference found - fail loudly, not silently accept and
    break later at run time.
    """
    if isinstance(value, dict):
        if "$ref" in value:
            ref = value["$ref"]
            if not isinstance(ref, dict) or "step" not in ref or "path" not in ref:
                raise ValidationError(
                    f"Step {step_number}: malformed $ref {ref!r} - expected "
                    f"{{'step': <int>, 'path': [<str>, ...]}}"
                )
            ref_step = ref["step"]
            if not isinstance(ref_step, int) or ref_step < 1 or ref_step >= step_number:
                raise ValidationError(
                    f"Step {step_number}: $ref points at step {ref_step}, which must be a "
                    f"positive integer referring to an EARLIER step (1..{step_number - 1})"
                )
            if ref_step > step_count:
                raise ValidationError(
                    f"Step {step_number}: $ref points at step {ref_step}, which doesn't exist "
                    f"in this template (only {step_count} step(s) defined)"
                )
            if not isinstance(ref["path"], list) or not all(isinstance(p, (str, int)) for p in ref["path"]):
                raise ValidationError(
                    f"Step {step_number}: $ref 'path' must be a list of strings and/or ints "
                    f"(strings for dict keys, ints for list indices), got {ref['path']!r}"
                )
            return  # a $ref dict is a leaf - don't also recurse into its own keys as literal input fields

        if "$param" in value:
            param_name = value["$param"]
            if not isinstance(param_name, str):
                raise ValidationError(f"Step {step_number}: malformed $param {param_name!r} - expected a string")
            if param_name not in declared_param_names:
                raise ValidationError(
                    f"Step {step_number}: $param references undeclared parameter '{param_name}' - "
                    f"declared parameters are {sorted(declared_param_names)}"
                )
            return

        for v in value.values():
            _validate_references(v, step_count, declared_param_names, step_number)

    elif isinstance(value, list):
        for item in value:
            _validate_references(item, step_count, declared_param_names, step_number)

    # scalars (str/int/float/bool/None) need no validation - they're literal values


def create_workflow_template(name: str, description: str, parameters: list[dict], steps: list[dict]) -> int:
    """
    Creates a new workflow template. Validates BEFORE inserting:
      - name is unique
      - every step's tool_name is a registered tool (any permission
        level - see module docstring)
      - every $ref/$param in every step's input resolves to something
        that will actually exist at execution time

    parameters: list of {"name": str, "description": str, "required": bool}
    steps: list of {"tool_name": str, "input": dict} - input may
        contain literal values, {"$ref": {...}}, and {"$param": "..."}
        anywhere in its structure, including nested inside lists/dicts.

    Returns the new template's id.
    """
    if not name or not name.strip():
        raise ValidationError("Workflow template name must be non-empty")

    if not steps:
        raise ValidationError("Workflow template must have at least one step")

    if get_workflow_template_by_name(name) is not None:
        raise ValidationError(f"A workflow template named '{name}' already exists")

    declared_param_names = set()
    for p in parameters:
        if "name" not in p:
            raise ValidationError(f"Parameter definition missing 'name': {p!r}")
        declared_param_names.add(p["name"])

    registry = get_registry()
    step_count = len(steps)

    for i, step in enumerate(steps, start=1):
        tool_name = step.get("tool_name")
        if tool_name not in registry:
            raise ValidationError(f"Step {i}: unknown tool '{tool_name}' is not registered")

        step_input = step.get("input", {})
        _validate_references(step_input, step_count, declared_param_names, i)

    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO workflow_templates (name, description, parameters_json, steps_json)
                VALUES (?, ?, ?, ?)
                """,
                (name, description, json.dumps(parameters), json.dumps(steps)),
            )
            template_id = cursor.lastrowid
    except DatabaseError:
        logger.error(f"Failed to create workflow template '{name}'")
        raise

    logger.info(f"Created workflow template {template_id} ('{name}', {step_count} step(s))")
    return template_id


def get_workflow_template(template_id: int) -> Optional[dict]:
    """Fetch a single workflow template by id. Returns None if not found."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM workflow_templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def get_workflow_template_by_name(name: str) -> Optional[dict]:
    """Fetch a single workflow template by its unique name. Returns None if not found."""
    with connection() as conn:
        row = conn.execute("SELECT * FROM workflow_templates WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def list_workflow_templates() -> list[dict]:
    """List all workflow templates, most recently created first."""
    with connection() as conn:
        rows = conn.execute("SELECT * FROM workflow_templates ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(row) for row in rows]


def delete_workflow_template(template_id: int) -> bool:
    """Delete a workflow template. Returns True if a row was deleted, False if not found."""
    with connection() as conn:
        cursor = conn.execute("DELETE FROM workflow_templates WHERE id = ?", (template_id,))
        return cursor.rowcount > 0


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "parameters": json.loads(row["parameters_json"]),
        "steps": json.loads(row["steps_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }