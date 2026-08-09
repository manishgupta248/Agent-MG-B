"""
Calendar READ tools - list events. READ permission.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from pydantic import BaseModel, Field

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.calendar._shared import get_calendar_service
from app.registry.intent_registry import intent_pattern


class ListEventsInput(BaseModel):
    calendar_id: str = Field(default="primary", description="Calendar id to query")
    time_min: str | None = Field(default=None, description="ISO 8601 datetime lower bound. Defaults to now (UTC) if omitted.")
    time_max: str | None = Field(default=None, description="ISO 8601 datetime upper bound. Defaults to time_min + 7 days if omitted.")
    query: str | None = Field(default=None, description="Free-text search across event fields (title, description, location, attendees)")
    max_results: int = Field(default=20, description="Maximum number of events to return")


@tool(
    name="calendar_list_events",
    description="List events on a Google Calendar within a time range, optionally filtered by free-text search. Defaults to the next 7 days on the primary calendar if no range given.",
    permission=PermissionLevel.READ,
    input_schema=ListEventsInput,
)
@intent_pattern(
    tool_name="calendar_list_events",
    pattern=r"what'?s on my calendar|show my calendar|list (?:my )?calendar events",
    group_mapping={},
)
def calendar_list_events(input_data: ListEventsInput) -> ToolResult:
    service = get_calendar_service()

    # RFC3339 UTC-with-'Z' is the least ambiguous form to send
    # regardless of the caller's own timezone.
    if input_data.time_min:
        time_min = input_data.time_min
        base = datetime.fromisoformat(input_data.time_min)
    else:
        base = datetime.now(dt_timezone.utc)
        time_min = base.strftime("%Y-%m-%dT%H:%M:%SZ")

    time_max = input_data.time_max or (base + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        response = service.events().list(
            calendarId=input_data.calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            q=input_data.query,
            maxResults=input_data.max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except Exception as e:
        raise ValidationError(f"Calendar list_events failed: {e}") from e

    events = []
    for ev in response.get("items", []):
        events.append({
            "id": ev.get("id"),
            "summary": ev.get("summary"),
            "start": ev.get("start"),
            "end": ev.get("end"),
            "location": ev.get("location"),
            "description": ev.get("description"),
            "attendees": [a.get("email") for a in ev.get("attendees", [])],
            "html_link": ev.get("htmlLink"),
        })

    return ToolResult(success=True, data=events)