"""
Second reference tool, nested one level deeper than ping.py, specifically
to verify recursive discovery actually recurses (this is the exact class
of bug walk_packages fixes over iter_modules).
"""

from pydantic import BaseModel

from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool


class DeepPingInput(BaseModel):
    pass


@tool(
    name="example_deep_ping",
    description="Reference tool nested 2 levels deep - proves recursive discovery works.",
    permission=PermissionLevel.READ,
    input_schema=DeepPingInput,
)
def deep_ping(input_data: DeepPingInput) -> ToolResult:
    return ToolResult(success=True, data="deep pong")