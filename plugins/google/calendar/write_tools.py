"""
Calendar WRITE tools - create, update, delete events. Create/update are
MODIFY permission; delete is DELETE permission (destructive, not
reversible via the API) - same Read/Modify/Delete/Admin tiering
established in M2, applied deliberately rather than defaulting
everything to MODIFY.
"""

from pydantic import BaseModel, Field, model_validator

from app.core.exceptions import ValidationError
from app.models.tool_result import ToolResult
from app.registry.tool_contract import PermissionLevel, tool
from plugins.google.calendar._shared import get_calendar_service, build_event_time, DEFAULT_TIMEZONE


class CreateEventInput(BaseModel):
    calendar_id: str = Field(default="primary", description="Calendar id to create the event on")
    summary: str = Field(description="Event title")
    start: str = Field(description="Start time - ISO 8601 datetime, or 'YYYY-MM-DD' if all_day=True")
    end: str = Field(description="End time - ISO 8601 datetime, or 'YYYY-MM-DD' if all_day=True")
    timezone: str = Field(default=DEFAULT_TIMEZONE, description="IANA timezone name. Ignored if all_day=True.")
    all_day: bool = Field(default=False, description="True for a date-only all-day event instead of a timed event")
    description: str | None = Field(default=None, description="Event description/notes")
    location: str | None = Field(default=None, description="Event location")
    attendees: list[str] = Field(default_factory=list, description="Attendee email addresses")


@tool(
    name="calendar_create_event",
    description="Create an event on a Google Calendar. Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=CreateEventInput,
)
def calendar_create_event(input_data: CreateEventInput) -> ToolResult:
    service = get_calendar_service()

    body = {
        "summary": input_data.summary,
        "start": build_event_time(input_data.start, input_data.timezone, input_data.all_day),
        "end": build_event_time(input_data.end, input_data.timezone, input_data.all_day),
    }
    if input_data.description:
        body["description"] = input_data.description
    if input_data.location:
        body["location"] = input_data.location
    if input_data.attendees:
        body["attendees"] = [{"email": e} for e in input_data.attendees]

    try:
        created = service.events().insert(calendarId=input_data.calendar_id, body=body).execute()
    except Exception as e:
        raise ValidationError(f"Failed to create Calendar event: {e}") from e

    return ToolResult(success=True, data={
        "id": created.get("id"),
        "summary": created.get("summary"),
        "start": created.get("start"),
        "end": created.get("end"),
        "html_link": created.get("htmlLink"),
    })


class UpdateEventInput(BaseModel):
    event_id: str = Field(description="Calendar event id to update, from calendar_list_events results")
    calendar_id: str = Field(default="primary", description="Calendar id the event lives on")
    summary: str | None = Field(default=None, description="New title. Omit to leave unchanged.")
    start: str | None = Field(default=None, description="New start time. Must be given together with 'end'.")
    end: str | None = Field(default=None, description="New end time. Must be given together with 'start'.")
    timezone: str = Field(default=DEFAULT_TIMEZONE, description="Used only if start/end are being updated and all_day=False")
    all_day: bool = Field(default=False, description="Set True if updating start/end to date-only values")
    description: str | None = Field(default=None, description="New description. Omit to leave unchanged.")
    location: str | None = Field(default=None, description="New location. Omit to leave unchanged.")
    attendees: list[str] | None = Field(default=None, description="New attendee list (replaces existing). Omit to leave unchanged.")

    @model_validator(mode="after")
    def _validate_update(self):
        if not any([self.summary, self.start, self.end, self.description, self.location, self.attendees is not None]):
            raise ValueError("Provide at least one field to update.")
        if bool(self.start) != bool(self.end):
            raise ValueError("start and end must be updated together, not one without the other.")
        return self


@tool(
    name="calendar_update_event",
    description="Update fields on an existing Calendar event (partial update - only specified fields change, everything else is left as-is). Requires approval.",
    permission=PermissionLevel.MODIFY,
    input_schema=UpdateEventInput,
)
def calendar_update_event(input_data: UpdateEventInput) -> ToolResult:
    service = get_calendar_service()

    body = {}
    if input_data.summary:
        body["summary"] = input_data.summary
    if input_data.start and input_data.end:
        body["start"] = build_event_time(input_data.start, input_data.timezone, input_data.all_day)
        body["end"] = build_event_time(input_data.end, input_data.timezone, input_data.all_day)
    if input_data.description is not None:
        body["description"] = input_data.description
    if input_data.location is not None:
        body["location"] = input_data.location
    if input_data.attendees is not None:
        body["attendees"] = [{"email": e} for e in input_data.attendees]

    try:
        # patch() applies a partial update server-side - fields not
        # included in body are left untouched, which is what makes the
        # "only specified fields change" contract in the description
        # actually true rather than aspirational.
        updated = service.events().patch(
            calendarId=input_data.calendar_id, eventId=input_data.event_id, body=body
        ).execute()
    except Exception as e:
        raise ValidationError(f"Failed to update Calendar event '{input_data.event_id}': {e}") from e

    return ToolResult(success=True, data={
        "id": updated.get("id"),
        "summary": updated.get("summary"),
        "start": updated.get("start"),
        "end": updated.get("end"),
        "location": updated.get("location"),
        "description": updated.get("description"),
        "html_link": updated.get("htmlLink"),
    })


class DeleteEventInput(BaseModel):
    event_id: str = Field(description="Calendar event id to delete")
    calendar_id: str = Field(default="primary", description="Calendar id the event lives on")


@tool(
    name="calendar_delete_event",
    description="Delete an event from a Google Calendar. Destructive and not reversible via the API. Requires approval.",
    permission=PermissionLevel.DELETE,
    input_schema=DeleteEventInput,
)
def calendar_delete_event(input_data: DeleteEventInput) -> ToolResult:
    service = get_calendar_service()

    try:
        # delete() returns an empty body (HTTP 204) on success - there's
        # no API payload worth trusting as "the data", so we build our
        # own confirmation dict from the input instead.
        service.events().delete(calendarId=input_data.calendar_id, eventId=input_data.event_id).execute()
    except Exception as e:
        raise ValidationError(f"Failed to delete Calendar event '{input_data.event_id}': {e}") from e

    return ToolResult(success=True, data={"deleted_event_id": input_data.event_id, "calendar_id": input_data.calendar_id})