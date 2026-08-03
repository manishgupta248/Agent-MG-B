"""
Shared helpers for PDF tools. Not a tool module itself.
"""

from pathlib import Path

from app.core.exceptions import ValidationError

VALID_PDF_EXTENSION = ".pdf"


def validate_pdf_path(file_path: str) -> Path:
    """Confirms the path exists and has a .pdf extension before opening."""
    path = Path(file_path)
    if not path.exists():
        raise ValidationError(f"File does not exist: {file_path}")
    if path.suffix.lower() != VALID_PDF_EXTENSION:
        raise ValidationError(f"Not a PDF file (expected .pdf): {file_path}")
    return path