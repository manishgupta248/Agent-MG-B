"""
Sheets READ tools - list sheet tabs and read cell ranges. READ
permission.
"""

from pydantic import BaseModel, Field

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.sheets._shared import get_sheets_service


class ListSheetsInput(BaseModel):
    spreadsheet_id: str = Field(description="Google Sheets spreadsheet id (from the sheet's URL or drive_search_files)")


@tool(
    name="sheets_list_sheets",
    description="List the individual sheet tabs within a Google Sheets spreadsheet (title, sheet id, row/column count). Use before sheets_read_range if the tab name isn't already known.",
    permission=PermissionLevel.READ,
    input_schema=ListSheetsInput,
)
def sheets_list_sheets(input_data: ListSheetsInput) -> ToolResult:
    service = get_sheets_service()
    try:
        meta = service.spreadsheets().get(
            spreadsheetId=input_data.spreadsheet_id, fields="properties.title,sheets.properties"
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to list sheets for spreadsheet '{input_data.spreadsheet_id}': {e}") from e

    sheets = []
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        grid = props.get("gridProperties", {})
        sheets.append({
            "sheet_id": props.get("sheetId"),
            "title": props.get("title"),
            "row_count": grid.get("rowCount"),
            "column_count": grid.get("columnCount"),
        })

    return ToolResult(success=True, data={
        "spreadsheet_title": meta.get("properties", {}).get("title"),
        "sheets": sheets,
    })


class ReadRangeInput(BaseModel):
    spreadsheet_id: str = Field(description="Google Sheets spreadsheet id")
    range: str = Field(description="A1 notation range, e.g. 'Sheet1!A1:C10'. Sheet name is required if the spreadsheet has more than one tab.")


@tool(
    name="sheets_read_range",
    description="Read cell values from a Google Sheets range in A1 notation (e.g. 'Sheet1!A1:C10').",
    permission=PermissionLevel.READ,
    input_schema=ReadRangeInput,
)
def sheets_read_range(input_data: ReadRangeInput) -> ToolResult:
    service = get_sheets_service()
    try:
        response = service.spreadsheets().values().get(
            spreadsheetId=input_data.spreadsheet_id, range=input_data.range
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to read range '{input_data.range}': {e}") from e

    return ToolResult(success=True, data={
        "range": response.get("range"),
        # Sheets omits trailing empty cells/rows entirely rather than
        # padding with blanks - rows can come back shorter than others
        # (or fewer rows than requested). Callers should not assume a
        # rectangular grid matching the requested range dimensions.
        "values": response.get("values", []),
    })