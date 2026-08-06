"""
Sheets WRITE tools - overwrite a range, or append rows. MODIFY
permission, approval-gated - same rationale as the other Google write
tools (Gmail send, Drive write, Calendar create/update): consequential
actions belong behind the existing call_tool approval framework, no
special-casing.
"""

from pydantic import BaseModel, Field

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.sheets._shared import get_sheets_service


class WriteRangeInput(BaseModel):
    spreadsheet_id: str = Field(description="Google Sheets spreadsheet id")
    range: str = Field(description="A1 notation range to write into, e.g. 'Sheet1!A1:C2'. Existing values in this range are overwritten - use sheets_append_rows instead to avoid overwriting.")
    values: list[list[str | int | float]] = Field(description="2D list of row values, e.g. [['Name', 'Score'], ['Alice', 90]]")
    value_input_option: str = Field(
        default="USER_ENTERED",
        description="'USER_ENTERED' parses input like the Sheets UI would (formulas, dates, numbers); 'RAW' stores exactly as given with no interpretation.",
    )


@tool(
    name="sheets_write_range",
    description="Overwrite a Google Sheets range with new values (A1 notation). Replaces existing content in the range. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=WriteRangeInput,
)
def sheets_write_range(input_data: WriteRangeInput) -> ToolResult:
    service = get_sheets_service()
    try:
        result = service.spreadsheets().values().update(
            spreadsheetId=input_data.spreadsheet_id,
            range=input_data.range,
            valueInputOption=input_data.value_input_option,
            body={"values": input_data.values},
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to write range '{input_data.range}': {e}") from e

    return ToolResult(success=True, data={
        "updated_range": result.get("updatedRange"),
        "updated_rows": result.get("updatedRows"),
        "updated_columns": result.get("updatedColumns"),
        "updated_cells": result.get("updatedCells"),
    })


class AppendRowsInput(BaseModel):
    spreadsheet_id: str = Field(description="Google Sheets spreadsheet id")
    range: str = Field(description="A1 notation range identifying the sheet/table to append after, e.g. 'Sheet1!A1' or just 'Sheet1'. Rows are added after the last row containing data.")
    values: list[list[str | int | float]] = Field(description="2D list of row values to append")
    value_input_option: str = Field(default="USER_ENTERED", description="Same semantics as sheets_write_range")


@tool(
    name="sheets_append_rows",
    description="Append rows to the end of a Google Sheets table without overwriting existing data. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=AppendRowsInput,
)
def sheets_append_rows(input_data: AppendRowsInput) -> ToolResult:
    service = get_sheets_service()
    try:
        result = service.spreadsheets().values().append(
            spreadsheetId=input_data.spreadsheet_id,
            range=input_data.range,
            valueInputOption=input_data.value_input_option,
            insertDataOption="INSERT_ROWS",
            body={"values": input_data.values},
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to append rows to '{input_data.range}': {e}") from e

    updates = result.get("updates", {})
    return ToolResult(success=True, data={
        "updated_range": updates.get("updatedRange"),
        "updated_rows": updates.get("updatedRows"),
        "updated_cells": updates.get("updatedCells"),
    })