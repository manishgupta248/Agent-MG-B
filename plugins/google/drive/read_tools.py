"""
Drive READ tools - search files and read text content where supported.
READ permission.
"""

import io

from pydantic import BaseModel, Field
from googleapiclient.http import MediaIoBaseDownload

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.drive._shared import (
    get_drive_service,
    EXPORTABLE_GOOGLE_TYPES,
    DIRECT_TEXT_MIME_PREFIXES,
)


class SearchFilesInput(BaseModel):
    query: str = Field(
        description=(
            "Raw Google Drive query syntax, e.g. "
            "\"name contains 'report' and mimeType='application/vnd.google-apps.spreadsheet'\""
        )
    )
    max_results: int = Field(default=20, description="Maximum number of files to return")


@tool(
    name="drive_search_files",
    description="Search Google Drive using native Drive query syntax, returning file metadata (id, name, mimeType, modifiedTime, size).",
    permission=PermissionLevel.READ,
    input_schema=SearchFilesInput,
)
def drive_search_files(input_data: SearchFilesInput) -> ToolResult:
    service = get_drive_service()
    try:
        response = service.files().list(
            q=input_data.query,
            pageSize=input_data.max_results,
            fields="files(id, name, mimeType, modifiedTime, size, parents)",
        ).execute()
    except Exception as e:
        raise ValidationError(f"Drive search failed: {e}") from e

    return ToolResult(success=True, data=response.get("files", []))


class ReadFileInput(BaseModel):
    file_id: str = Field(description="Google Drive file id, from drive_search_files results")
    max_chars: int = Field(default=50000, description="Truncate extracted text to this many characters")


@tool(
    name="drive_read_file",
    description=(
        "Read a Drive file's text content. Supports Google Docs, Google Sheets "
        "(first sheet only, exported as CSV), and plain text/CSV files. Other "
        "file types return metadata only with content_extracted=False - this "
        "is a successful result, not an error, since 'unsupported type' is "
        "expected and informative rather than exceptional."
    ),
    permission=PermissionLevel.READ,
    input_schema=ReadFileInput,
)
def drive_read_file(input_data: ReadFileInput) -> ToolResult:
    service = get_drive_service()
    try:
        meta = service.files().get(
            fileId=input_data.file_id, fields="id, name, mimeType, modifiedTime, size"
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to fetch Drive file metadata for '{input_data.file_id}': {e}") from e

    mime_type = meta.get("mimeType", "")
    content = None
    extracted = False
    reason = None

    try:
        if mime_type in EXPORTABLE_GOOGLE_TYPES:
            export_mime = EXPORTABLE_GOOGLE_TYPES[mime_type]
            raw = service.files().export(fileId=input_data.file_id, mimeType=export_mime).execute()
            content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            extracted = True
        elif mime_type.startswith(DIRECT_TEXT_MIME_PREFIXES):
            buf = io.BytesIO()
            request = service.files().get_media(fileId=input_data.file_id)
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            content = buf.getvalue().decode("utf-8", errors="replace")
            extracted = True
        else:
            reason = f"Content extraction not supported for mimeType '{mime_type}' - metadata only."
    except Exception as e:
        raise ValidationError(f"Failed to extract content from Drive file '{input_data.file_id}': {e}") from e

    if content is not None and len(content) > input_data.max_chars:
        content = content[: input_data.max_chars]

    return ToolResult(success=True, data={
        "id": meta.get("id"),
        "name": meta.get("name"),
        "mime_type": mime_type,
        "modified_time": meta.get("modifiedTime"),
        "content_extracted": extracted,
        "content": content,
        "reason": reason,
    })