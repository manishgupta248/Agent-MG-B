"""
Shared helpers for Excel tools. Not a tool module itself - no @tool
decorators here, just the common file-opening/validation logic every
Excel tool in this package uses.
"""

from pathlib import Path

import openpyxl
from openpyxl.workbook import Workbook

from app.core.exceptions import ValidationError

VALID_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


def validate_excel_path(file_path: str) -> Path:
    """
    Confirms the path exists and has a valid Excel extension BEFORE
    attempting to open it - a clear ValidationError here beats whatever
    cryptic error openpyxl would raise on a missing/wrong-type file.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValidationError(f"File does not exist: {file_path}")
    if path.suffix.lower() not in VALID_EXCEL_EXTENSIONS:
        raise ValidationError(
            f"Not a valid Excel file (expected {VALID_EXCEL_EXTENSIONS}): {file_path}"
        )
    return path


def open_workbook_readonly(file_path: str) -> Workbook:
    """
    Opens a workbook in STREAMING READ-ONLY mode (read_only=True) - this
    is the actual mechanism behind the project's "streaming reads" 8GB
    RAM discipline (Section 2). Every read tool in this package must
    open workbooks through this function, never load_workbook() directly.

    data_only=True returns formula cells' last-CALCULATED value rather
    than the formula string itself (e.g. 15 instead of "=SUM(A1:A5)") -
    set explicitly since that's almost always what's wanted when an
    agent is reading a spreadsheet a human already has real data in.
    """
    path = validate_excel_path(file_path)
    try:
        return openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as e:
        raise ValidationError(f"Failed to open Excel file '{file_path}': {e}") from e