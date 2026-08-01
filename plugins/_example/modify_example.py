"""
Second reference tool - declares PermissionLevel.MODIFY specifically so
the approval-gating tests in M2-S2 have a non-READ tool to exercise.
Does nothing destructive itself; it's a gating test fixture, not a real
capability.
"""

from pydantic import BaseModel, Field

from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool


class ModifyExampleInput(BaseModel):
    value: str = Field(default="changed", description="Placeholder value")


@tool(
    name="example_modify",
    description="Reference tool with MODIFY permission - used to test approval gating, does nothing real.",
    permission=PermissionLevel.MODIFY,
    input_schema=ModifyExampleInput,
)
def modify_example(input_data: ModifyExampleInput) -> ToolResult:
    return ToolResult(success=True, data=f"would have changed: {input_data.value}")