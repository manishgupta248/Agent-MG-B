"""
Shared helpers for Drive tools. Not a tool module itself.
"""

from pathlib import Path

from googleapiclient.discovery import build

from app.core.google_auth import get_credentials
from app.core.exceptions import ValidationError


def get_drive_service():
    """
    Builds a fresh Drive API service object using the shared OAuth
    credentials (app.core.google_auth). Same rebuild-per-call pattern
    as Gmail's get_gmail_service - credentials can refresh mid-session,
    and the build() call itself is cheap.
    """
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


# Google Workspace native types don't have raw bytes in Drive - only
# Google's internal format - so they need export_media()/export()
# rather than get_media(). Anything not listed here is either a plain
# file (direct download works) or unsupported for text extraction.
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

# mimeTypes we know how to text-extract, mapped to the export format
# to request for each. NOTE: Sheets export is first-sheet-only (Drive
# export API limitation) - same kind of documented limitation as the
# docx find_and_replace run-level constraint from M8.
EXPORTABLE_GOOGLE_TYPES = {
    GOOGLE_DOC_MIME: "text/plain",
    GOOGLE_SHEET_MIME: "text/csv",
}

# Plain files (not Google-native) we'll direct-download and decode as
# text rather than treating as opaque binary.
DIRECT_TEXT_MIME_PREFIXES = ("text/",)


def validate_local_path(path: str) -> Path:
    """
    Confirms a local path exists and is a file before attempting an
    upload - same fail-fast-before-API-call discipline as
    validate_excel_path/validate_docx_path in the other plugin families.
    """
    p = Path(path)
    if not p.exists():
        raise ValidationError(f"Local file not found: {path}")
    if not p.is_file():
        raise ValidationError(f"Path is not a file: {path}")
    return p