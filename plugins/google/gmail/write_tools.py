"""
Gmail WRITE tools - send_message. MODIFY permission, approval-gated -
sending an email is exactly the kind of destructive/consequential
action Section 2's approval gate exists for. No special-casing outside
the existing call_tool approval framework.
"""

import base64
from email.mime.text import MIMEText

from pydantic import BaseModel, Field

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.gmail._shared import get_gmail_service


class SendMessageInput(BaseModel):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Plain-text email body")


@tool(
    name="gmail_send_message",
    description="Send a plain-text email via Gmail. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=SendMessageInput,
)
def gmail_send_message(input_data: SendMessageInput) -> ToolResult:
    service = get_gmail_service()

    message = MIMEText(input_data.body)
    message["To"] = input_data.to
    message["Subject"] = input_data.subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:
        raise ValidationError(f"Failed to send Gmail message: {e}") from e

    return ToolResult(success=True, data={"message_id": sent["id"], "to": input_data.to, "subject": input_data.subject})