from app.core.logging_setup import configure_logging
from app.registry.discovery import discover_tools
from app.core.call_tool import call_tool
from app.core.approval import AutoApproveHandler

configure_logging()
discover_tools()

# List upcoming events (default: next 7 days, primary calendar)
list_result = call_tool("calendar_list_events", {})
print(f"Found {len(list_result.data)} upcoming events:")
for e in list_result.data:
    print(f"  - {e['summary']} ({e['start']})")

# Create a test event - adjust the date below if 2026-08-10 has already passed by the time you run this.
create_result = call_tool(
    "calendar_create_event",
    {
        "summary": "M9-S4 Test Event",
        "start": "2026-08-10T15:00:00",
        "end": "2026-08-10T16:00:00",
        "description": "Created by scratch_test_calendar.py",
    },
    approval_handler=AutoApproveHandler(),
)
print(f"\nCreated event: {create_result.data}")
event_id = create_result.data["id"]

# Update it - change title and add a location
update_result = call_tool(
    "calendar_update_event",
    {"event_id": event_id, "summary": "M9-S4 Test Event (Updated)", "location": "Test Location"},
    approval_handler=AutoApproveHandler(),
)
print(f"\nUpdated event: {update_result.data}")

# Delete it
delete_result = call_tool(
    "calendar_delete_event",
    {"event_id": event_id},
    approval_handler=AutoApproveHandler(),
)
print(f"\nDeleted event: {delete_result.data}")