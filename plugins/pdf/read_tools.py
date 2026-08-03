"""
PDF READ tools - metadata, page-ranged text extraction, search.
All READ permission (no approval gate).

RAM discipline note (Section 2/3): PDFs have no native lazy-loading mode
like openpyxl's read_only=True. The equivalent discipline here is
PAGE-RANGED processing - pdf_extract_text only parses the requested
page range (pdfplumber opens lazily per-page), and pdf_search_text
processes one page at a time and stops early once max_results is hit,
rather than ever extracting the full document's text into memory at once.

pypdf is used for lightweight metadata (page count, title, author) -
no layout analysis needed. pdfplumber is used for actual text
extraction/search - much better at preserving real reading order,
tables, and columns, but heavier per page, so it's reserved for when
real text extraction is actually requested.
"""

from typing import Optional

import pdfplumber
from pypdf import PdfReader
from pydantic import BaseModel, Field

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.pdf._shared import validate_pdf_path

DEFAULT_MAX_PAGES_PER_EXTRACT = 50


class GetMetadataInput(BaseModel):
    file_path: str = Field(description="Path to the .pdf file")


@tool(
    name="pdf_get_metadata",
    description="Get a PDF's page count and document metadata (title, author, etc.) without extracting any text.",
    permission=PermissionLevel.READ,
    input_schema=GetMetadataInput,
)
def pdf_get_metadata(input_data: GetMetadataInput) -> ToolResult:
    path = validate_pdf_path(input_data.file_path)
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        raise ValidationError(f"Failed to open PDF '{input_data.file_path}': {e}") from e

    meta = reader.metadata or {}
    return ToolResult(success=True, data={
        "page_count": len(reader.pages),
        "title": meta.get("/Title"),
        "author": meta.get("/Author"),
        "subject": meta.get("/Subject"),
        "creator": meta.get("/Creator"),
    })


class ExtractTextInput(BaseModel):
    file_path: str = Field(description="Path to the .pdf file")
    start_page: int = Field(default=1, description="1-indexed first page to extract")
    end_page: Optional[int] = Field(
        default=None,
        description=f"1-indexed last page to extract (inclusive). Defaults to start_page + {DEFAULT_MAX_PAGES_PER_EXTRACT} if omitted, to avoid an unbounded whole-document extraction.",
    )


@tool(
    name="pdf_extract_text",
    description=(
        "Extract text from a page range of a PDF, using layout-aware extraction (pdfplumber). "
        "Only the requested page range is parsed - never the whole document at once."
    ),
    permission=PermissionLevel.READ,
    input_schema=ExtractTextInput,
)
def pdf_extract_text(input_data: ExtractTextInput) -> ToolResult:
    path = validate_pdf_path(input_data.file_path)
    start = max(1, input_data.start_page)
    end = input_data.end_page if input_data.end_page is not None else start + DEFAULT_MAX_PAGES_PER_EXTRACT - 1

    try:
        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            end = min(end, total_pages)
            if start > total_pages:
                raise ValidationError(
                    f"start_page {start} exceeds document length ({total_pages} pages)"
                )

            pages_text = []
            for page_num in range(start, end + 1):
                page = pdf.pages[page_num - 1]  # pdfplumber is 0-indexed internally
                text = page.extract_text() or ""
                pages_text.append({"page": page_num, "text": text})

        return ToolResult(success=True, data={
            "start_page": start,
            "end_page": end,
            "total_pages": total_pages,
            "pages": pages_text,
        })
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"Failed to extract text from PDF '{input_data.file_path}': {e}") from e


class SearchTextInput(BaseModel):
    file_path: str = Field(description="Path to the .pdf file")
    query: str = Field(description="Text to search for (case-insensitive substring match)")
    max_results: int = Field(default=20, description="Stop after this many matching pages")


@tool(
    name="pdf_search_text",
    description="Search a PDF for pages whose text contains the given query, processing one page at a time.",
    permission=PermissionLevel.READ,
    input_schema=SearchTextInput,
)
def pdf_search_text(input_data: SearchTextInput) -> ToolResult:
    path = validate_pdf_path(input_data.file_path)
    query_lower = input_data.query.lower()
    matches = []

    try:
        with pdfplumber.open(str(path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if query_lower in text.lower():
                    # Small snippet around the first occurrence, not the whole page,
                    # to keep the result set light.
                    idx = text.lower().find(query_lower)
                    snippet_start = max(0, idx - 40)
                    snippet = text[snippet_start:idx + len(input_data.query) + 40]
                    matches.append({"page": page_num, "snippet": snippet.strip()})
                    if len(matches) >= input_data.max_results:
                        return ToolResult(success=True, data={"matches": matches, "truncated": True})

        return ToolResult(success=True, data={"matches": matches, "truncated": False})
    except Exception as e:
        raise ValidationError(f"Failed to search PDF '{input_data.file_path}': {e}") from e