"""
The single shared execution pipeline every tier (Tier 1 regex, Tier 1.5
pipelines, Tier 2 fuzzy, Tier 3 LLM, Tier 4 LangGraph) routes through to
actually invoke a tool. No tier ever calls a registered tool's function
directly - always through call_tool.

Structural fixes encoded here from documented prior-build bugs:
  - Parameter is named `tool_name`, not `name` - a tool having its own
    `name` parameter (e.g. create_drive_folder(name=...)) previously
    collided with call_tool's own signature.
  - Return type is always ToolResult, never None - every code path here
    either returns a populated ToolResult or raises; there is no bare
    `return` and no falling off the end of the function, which is what
    let a prior refactor silently return None on the success path.
  - Input validation happens HERE, before the tool function ever runs -
    not inside individual tools - so a tool can never accidentally skip
    validating its own input.

Approval-gating (permission-level policy) is NOT yet wired in here -
that's M2-S2. This step is deliberately scoped to prove call_tool itself
is correct and tested standalone before approval logic is layered on.
"""

import json
import time

from loguru import logger
from pydantic import ValidationError as PydanticValidationError

from app.core.database import connection
from app.core.exceptions import ToolExecutionError, ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import get_registry


def _log_execution(
    tool_name: str,
    input_dict: dict,
    result: ToolResult | None,
    error_message: str | None,
    duration_ms: int,
    run_id: str | None,
) -> None:
    """
    Writes one row to execution_history. Called from call_tool's finally
    path so logging happens whether the call succeeded or failed - no
    tool, and no tier calling call_tool, has to remember to do this
    itself.
    """
    try:
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO execution_history
                    (run_id, tool_name, input_json, output_json, success, error_message, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tool_name,
                    json.dumps(input_dict, default=str),
                    json.dumps(result.model_dump(), default=str) if result else None,
                    1 if (result and result.success) else 0,
                    error_message,
                    duration_ms,
                ),
            )
    except Exception as e:
        # Audit logging must never itself crash the calling tier - log
        # loudly and move on. A missing audit row is bad; a crashed
        # agent because logging failed is worse.
        logger.error(f"Failed to write execution_history row for tool '{tool_name}': {e}")


def call_tool(tool_name: str, input_dict: dict, run_id: str | None = None) -> ToolResult:
    """
    Look up a registered tool by name, validate input_dict against its
    input_schema, invoke it, log the outcome to execution_history, and
    return a ToolResult.

    Args:
        tool_name: registered tool name (NOT `name` - see module docstring)
        input_dict: raw input, validated against the tool's Pydantic input_schema
        run_id: optional grouping id for multi-step runs (used starting M10/M13)

    Returns:
        ToolResult - always. Never None.

    Raises:
        ToolExecutionError: tool_name not found, input validation failed,
            or the tool function itself raised during execution.
    """
    start = time.monotonic()
    registry = get_registry()

    # --- Lookup ---
    registered = registry.get(tool_name)
    if registered is None:
        error_message = f"Unknown tool: '{tool_name}' is not registered"
        logger.error(error_message)
        _log_execution(tool_name, input_dict, None, error_message, 0, run_id)
        raise ToolExecutionError(error_message)

    # --- Input validation (BEFORE the tool function ever runs) ---
    try:
        validated_input = registered.input_schema(**input_dict)
    except PydanticValidationError as e:
        error_message = f"Input validation failed for tool '{tool_name}': {e}"
        logger.error(error_message)
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_execution(tool_name, input_dict, None, error_message, duration_ms, run_id)
        # Wrapped re-raise per exception-handling rule - never a bare
        # re-raise of the Pydantic error outside this except block.
        raise ValidationError(error_message) from e

    # --- Invocation ---
    try:
        result: ToolResult = registered.func(validated_input)
    except Exception as e:
        error_message = f"Tool '{tool_name}' raised during execution: {e}"
        logger.error(error_message)
        duration_ms = int((time.monotonic() - start) * 1000)
        _log_execution(tool_name, input_dict, None, error_message, duration_ms, run_id)
        raise ToolExecutionError(error_message) from e

    duration_ms = int((time.monotonic() - start) * 1000)
    _log_execution(tool_name, input_dict, result, None, duration_ms, run_id)

    logger.info(f"Tool '{tool_name}' executed successfully in {duration_ms}ms")
    return result