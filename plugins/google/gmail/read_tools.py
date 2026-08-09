"""
Gmail READ tools - search and read messages. READ permission.
"""

import base64

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.gmail._shared import get_gmail_service
from app.registry.intent_registry import intent_pattern


class SearchMessagesInput(BaseModel):
    query: str = Field(description="Gmail search query, e.g. 'from:boss@company.com is:unread'")
    max_results: int = Field(default=20, description="Maximum number of messages to return")


@tool(
    name="gmail_search_messages",
    description="Search Gmail using native Gmail query syntax (from:, subject:, is:unread, etc.), returning message summaries.",
    permission=PermissionLevel.READ,
    input_schema=SearchMessagesInput,
)
@intent_pattern(
    tool_name="gmail_search_messages",
    pattern=r"search (?:my )?(?:gmail|email|inbox) for (?P<q>.+)",
    group_mapping={"q": "query"},
)
def gmail_search_messages(input_data: SearchMessagesInput) -> ToolResult:
    service = get_gmail_service()
    try:
        response = service.users().messages().list(
            userId="me", q=input_data.query, maxResults=input_data.max_results
        ).execute()
    except Exception as e:
        raise ValidationError(f"Gmail search failed: {e}") from e

    message_ids = response.get("messages", [])
    summaries = []
    for msg_ref in message_ids:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        summaries.append({
            "id": msg["id"],
            "from": headers.get("From"),
            "subject": headers.get("Subject"),
            "date": headers.get("Date"),
            "snippet": msg.get("snippet"),
        })

    return ToolResult(success=True, data=summaries)


class ReadMessageInput(BaseModel):
    message_id: str = Field(description="Gmail message id, from gmail_search_messages results")


def _find_part_by_mime(payload, mime_type: str) -> str:
    """
    Recursively walks a Gmail MIME payload looking for the first part
    matching mime_type, decoding its base64url body if found. Returns
    empty string if no matching part exists anywhere in the tree -
    caller decides what to do about that (see _extract_body_text).
    """
    if payload.get("mimeType") == mime_type and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _find_part_by_mime(part, mime_type)
        if text:
            return text

    return ""


def _extract_body_text(payload) -> str:
    """
    Extracts a readable body from a Gmail message's MIME payload.
    Prefers text/plain. Falls back to text/html stripped to plain text
    via BeautifulSoup, since many senders (marketing/newsletter emails
    especially) send HTML-only with no text/plain alternative at all -
    without this fallback, gmail_read_message silently "succeeds" with
    an empty body on such messages.
    """
    plain = _find_part_by_mime(payload, "text/plain")
    if plain:
        return plain

    html_body = _find_part_by_mime(payload, "text/html")
    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        # separator="\n" preserves some paragraph/line structure instead
        # of collapsing the whole email into one run-on line
        text = soup.get_text(separator="\n")
        # collapse runs of blank lines left behind by stripped tags
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    return ""


@tool(
    name="gmail_read_message",
    description="Read the full plain-text body and headers of a single Gmail message by id.",
    permission=PermissionLevel.READ,
    input_schema=ReadMessageInput,
)
def gmail_read_message(input_data: ReadMessageInput) -> ToolResult:
    service = get_gmail_service()
    try:
        msg = service.users().messages().get(
            userId="me", id=input_data.message_id, format="full"
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to read Gmail message '{input_data.message_id}': {e}") from e

    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    body_text = _extract_body_text(msg["payload"])

    return ToolResult(success=True, data={
        "id": msg["id"],
        "from": headers.get("From"),
        "to": headers.get("To"),
        "subject": headers.get("Subject"),
        "date": headers.get("Date"),
        "body": body_text,
    })