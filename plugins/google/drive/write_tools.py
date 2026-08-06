"""
Drive WRITE tools - upload files, create folders, move/rename files.
MODIFY permission, approval-gated - same rationale as Gmail send: these
are consequential remote actions that belong behind the existing
call_tool approval framework, no special-casing.

Note: unlike the Excel/Word write tools, there's no local-file atomic-
save concern here - these are remote API writes, not local file
mutations, so tempfile+os.replace doesn't apply. The equivalent risk
(partial/inconsistent state) is Google's problem to solve server-side.
"""

import io

from pydantic import BaseModel, Field, model_validator
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.drive._shared import get_drive_service, validate_local_path, GOOGLE_FOLDER_MIME


class UploadFileInput(BaseModel):
    name: str = Field(description="Name for the uploaded file in Drive")
    local_path: str | None = Field(default=None, description="Local file path to upload. Mutually exclusive with 'content'.")
    content: str | None = Field(default=None, description="Raw text content to upload as a plain-text file. Mutually exclusive with 'local_path'.")
    mime_type: str = Field(default="text/plain", description="MIME type for 'content' uploads. Ignored for local_path (auto-detected by the API client).")
    parent_folder_id: str | None = Field(default=None, description="Drive folder id to upload into. Omit for My Drive root.")

    @model_validator(mode="after")
    def _exactly_one_source(self):
        # Fail loudly at validation time rather than ambiguously
        # preferring one source if both/neither given - same discipline
        # as the docx tools' input validation from M8.
        if bool(self.local_path) == bool(self.content):
            raise ValueError("Provide exactly one of 'local_path' or 'content', not both or neither.")
        return self


@tool(
    name="drive_upload_file",
    description="Upload a new file to Google Drive, from either a local file path or raw text content. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=UploadFileInput,
)
def drive_upload_file(input_data: UploadFileInput) -> ToolResult:
    service = get_drive_service()

    file_metadata = {"name": input_data.name}
    if input_data.parent_folder_id:
        file_metadata["parents"] = [input_data.parent_folder_id]

    if input_data.local_path:
        path = validate_local_path(input_data.local_path)
        media = MediaFileUpload(str(path), resumable=False)
    else:
        buf = io.BytesIO(input_data.content.encode("utf-8"))
        media = MediaIoBaseUpload(buf, mimetype=input_data.mime_type, resumable=False)

    try:
        created = service.files().create(
            body=file_metadata, media_body=media, fields="id, name, mimeType, webViewLink"
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to upload file to Drive: {e}") from e

    return ToolResult(success=True, data=created)


class CreateFolderInput(BaseModel):
    name: str = Field(description="Name for the new folder")
    parent_folder_id: str | None = Field(default=None, description="Drive folder id to create inside. Omit for My Drive root.")
    allow_duplicate_name: bool = Field(
        default=False,
        description="Drive allows multiple folders with identical names in the same parent. Set True to bypass the duplicate-name check.",
    )


@tool(
    name="drive_create_folder",
    description="Create a new folder in Google Drive. Refuses to create a duplicate-named folder in the same parent unless allow_duplicate_name=True. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=CreateFolderInput,
)
def drive_create_folder(input_data: CreateFolderInput) -> ToolResult:
    service = get_drive_service()

    if not input_data.allow_duplicate_name:
        # Drive has no filesystem-style name-uniqueness constraint,
        # unlike Excel sheet names - this check is a deliberate safety
        # convenience we're adding, not something the API enforces.
        parent = input_data.parent_folder_id or "root"
        query = (
            f"name = '{input_data.name}' and mimeType = '{GOOGLE_FOLDER_MIME}' "
            f"and '{parent}' in parents and trashed = false"
        )
        try:
            existing = service.files().list(q=query, fields="files(id, name)").execute()
        except Exception as e:
            raise ValidationError(f"Failed to check for duplicate folder name: {e}") from e

        if existing.get("files"):
            raise ValidationError(
                f"A folder named '{input_data.name}' already exists in this location. "
                f"Set allow_duplicate_name=True to create another anyway."
            )

    file_metadata = {"name": input_data.name, "mimeType": GOOGLE_FOLDER_MIME}
    if input_data.parent_folder_id:
        file_metadata["parents"] = [input_data.parent_folder_id]

    try:
        created = service.files().create(body=file_metadata, fields="id, name, webViewLink").execute()
    except Exception as e:
        raise ValidationError(f"Failed to create Drive folder: {e}") from e

    return ToolResult(success=True, data=created)


class MoveOrRenameFileInput(BaseModel):
    file_id: str = Field(description="Drive file or folder id to move and/or rename")
    new_name: str | None = Field(default=None, description="New name for the file/folder. Omit to leave unchanged.")
    new_parent_folder_id: str | None = Field(default=None, description="Folder id to move the file into. Omit to leave in its current location.")

    @model_validator(mode="after")
    def _at_least_one_change(self):
        if not self.new_name and not self.new_parent_folder_id:
            raise ValueError("Provide at least one of 'new_name' or 'new_parent_folder_id'.")
        return self


@tool(
    name="drive_move_or_rename_file",
    description="Rename a Drive file/folder, move it to a different parent folder, or both. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=MoveOrRenameFileInput,
)
def drive_move_or_rename_file(input_data: MoveOrRenameFileInput) -> ToolResult:
    service = get_drive_service()

    body = {}
    if input_data.new_name:
        body["name"] = input_data.new_name

    kwargs = {"fileId": input_data.file_id, "body": body, "fields": "id, name, parents"}

    if input_data.new_parent_folder_id:
        # Drive move semantics: add the new parent, remove ALL current
        # parents. update() needs the current parent list to remove
        # them, so we fetch it first - there's no "just move" verb.
        try:
            current = service.files().get(fileId=input_data.file_id, fields="parents").execute()
        except Exception as e:
            raise ValidationError(f"Failed to fetch current parents for '{input_data.file_id}': {e}") from e

        existing_parents = ",".join(current.get("parents", []))
        kwargs["addParents"] = input_data.new_parent_folder_id
        if existing_parents:
            kwargs["removeParents"] = existing_parents

    try:
        updated = service.files().update(**kwargs).execute()
    except Exception as e:
        raise ValidationError(f"Failed to move/rename Drive file '{input_data.file_id}': {e}") from e

    return ToolResult(success=True, data=updated)