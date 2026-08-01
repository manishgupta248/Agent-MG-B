"""
Reference/template plugin. Not a real capability - shows the minimal
shape every future plugin (Excel, PDF, Gmail, etc.) must follow.
Kept permanently as living documentation for plugin authors.
"""

from pydantic import BaseModel, Field

from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool


class PingInput(BaseModel):
    """Every tool's input must be a Pydantic model, even a trivial one."""
    message: str = Field(default="pong", description="Message to echo back")


@tool(
    name="example_ping",
    description="Reference/template tool - echoes back the input message.",
    permission=PermissionLevel.READ,
    input_schema=PingInput,
)
def ping(input_data: PingInput) -> ToolResult:
    return ToolResult(success=True, data=input_data.message)