"""
Shared result shape returned by every tool. Defined in app/models (not
app/registry) because both the registry and, later, the LLM planner /
LangGraph orchestration (M14/M15) need to import this without importing
the whole registry module.
"""

from typing import Any, Optional

from pydantic import BaseModel


class ToolResult(BaseModel):
    """
    Standard return shape for every tool call, whatever tier invoked it.

    success/data/error mirror a typical Result type. `data` is left as
    Any rather than a generic, since tools return wildly different
    shapes (a dict, a list, a bare string) - callers are expected to
    know what shape to expect from a given tool's documented contract.
    """

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None