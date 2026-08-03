"""
Shared helpers for Word tools. Not a tool module itself.
"""

import os
import tempfile
from pathlib import Path

from app.core.exceptions import ValidationError

VALID_DOCX_EXTENSION = ".docx"


def validate_docx_path(file_path: str, must_exist: bool = True) -> Path:
    """
    Confirms extension is .docx. If must_exist is True (the default, for
    read/append/replace operations), also confirms the file exists.
    must_exist=False is used by docx_create_document, which is creating
    a NEW file and should not require one to already be there.
    """
    path = Path(file_path)
    if must_exist and not path.exists():
        raise ValidationError(f"File does not exist: {file_path}")
    if path.suffix.lower() != VALID_DOCX_EXTENSION:
        raise ValidationError(f"Not a Word file (expected .docx): {file_path}")
    return path


def save_docx_atomically(document, target_path: Path) -> None:
    """
    Same atomic temp-file-then-replace pattern as Excel's
    _save_atomically (plugins/excel/write_tools.py) - saves to a temp
    file in the SAME directory as target_path, then os.replace()'s it
    onto the original. The original is only ever fully replaced or left
    completely untouched, never partially written.
    """
    fd, temp_path_str = tempfile.mkstemp(suffix=".docx", dir=str(target_path.parent))
    os.close(fd)
    temp_path = Path(temp_path_str)
    try:
        document.save(str(temp_path))
        os.replace(str(temp_path), str(target_path))
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise