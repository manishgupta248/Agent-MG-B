from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.core.call_tool import call_tool
from app.core.approval import AutoApproveHandler

configure_logging()
discover_tools()

# Search - broad query that should match something in most Drives.
search_result = call_tool("drive_search_files", {"query": "trashed = false", "max_results": 5})
print(f"Search found {len(search_result.data)} files:")
for f in search_result.data:
    print(f"  - {f['name']} ({f['mimeType']}) id={f['id']}")

if search_result.data:
    first_id = search_result.data[0]["id"]
    read_result = call_tool("drive_read_file", {"file_id": first_id})
    print(f"\nRead first file: content_extracted={read_result.data['content_extracted']}")
    if read_result.data["content_extracted"]:
        print(f"Content preview (first 200 chars): {read_result.data['content'][:200]}")
    else:
        print(f"Reason: {read_result.data['reason']}")

# Create a test folder
folder_result = call_tool(
    "drive_create_folder",
    {"name": "PersonalAgent_M9S3_Test"},
    approval_handler=AutoApproveHandler(),
)
print(f"\nCreated folder: {folder_result.data}")
folder_id = folder_result.data["id"]

# Upload a text file into that folder
upload_result = call_tool(
    "drive_upload_file",
    {"name": "test_upload.txt", "content": "If you see this, drive_upload_file works.", "parent_folder_id": folder_id},
    approval_handler=AutoApproveHandler(),
)
print(f"\nUploaded file: {upload_result.data}")
file_id = upload_result.data["id"]

# Rename it
rename_result = call_tool(
    "drive_move_or_rename_file",
    {"file_id": file_id, "new_name": "test_upload_renamed.txt"},
    approval_handler=AutoApproveHandler(),
)
print(f"\nRenamed file: {rename_result.data}")