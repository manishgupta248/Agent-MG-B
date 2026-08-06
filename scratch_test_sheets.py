from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.core.call_tool import call_tool
from app.core.approval import AutoApproveHandler

configure_logging()
discover_tools()

spreadsheet_id = input("Enter the spreadsheet id of a BLANK TEST sheet (not a real one): ")

# List tabs
list_result = call_tool("sheets_list_sheets", {"spreadsheet_id": spreadsheet_id})
print(f"\nSpreadsheet: {list_result.data['spreadsheet_title']}")
print(f"Tabs: {[s['title'] for s in list_result.data['sheets']]}")

first_tab = list_result.data["sheets"][0]["title"]

# Write to a far corner (column Z) so we don't clobber anything even
# if you accidentally point this at a non-blank sheet.
write_range = f"{first_tab}!Z1:Z2"
write_result = call_tool(
    "sheets_write_range",
    {"spreadsheet_id": spreadsheet_id, "range": write_range, "values": [["Test1"], ["Test2"]]},
    approval_handler=AutoApproveHandler(),
)
print(f"\nWrite result: {write_result.data}")

# Read it back
read_result = call_tool("sheets_read_range", {"spreadsheet_id": spreadsheet_id, "range": write_range})
print(f"\nRead back: {read_result.data}")

# Append a row after the same range
append_result = call_tool(
    "sheets_append_rows",
    {"spreadsheet_id": spreadsheet_id, "range": write_range, "values": [["Test3 (appended)"]]},
    approval_handler=AutoApproveHandler(),
)
print(f"\nAppend result: {append_result.data}")