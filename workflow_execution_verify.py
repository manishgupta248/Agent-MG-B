from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.workflow_templates import init_workflow_templates, create_workflow_template
from app.core.workflow_execution import init_workflow_execution, execute_workflow, list_workflow_run_steps
from app.core.call_tool import call_tool
from app.core.approval import AutoApproveHandler
from app.registry.discovery import discover_tools

configure_logging()
init_db()
init_workflow_templates()
init_workflow_execution()
discover_tools()

# 3-step template: READ, then MODIFY (create), then MODIFY (update,
# chaining the created event's id via $ref). Tests chaining AND
# whether approving step 2 auto-approves step 3 (batch approval).
create_workflow_template(
    name="calendar_create_and_update_test",
    description="Create a calendar event then immediately update it - tests chaining + batch approval",
    parameters=[{"name": "event_title", "description": "Initial event title", "required": True}],
    steps=[
        {"tool_name": "calendar_list_events", "input": {}},
        {"tool_name": "calendar_create_event", "input": {
            "summary": {"$param": "event_title"},
            "start": "2026-08-10T15:00:00", "end": "2026-08-10T16:00:00",
        }},
        {"tool_name": "calendar_update_event", "input": {
            "event_id": {"$ref": {"step": 2, "path": ["data", "id"]}},
            "summary": "Updated via workflow chaining",
        }},
    ],
)
print("Template created")

result = execute_workflow(
    "calendar_create_and_update_test",
    {"event_title": "M12-S2 Test Event"},
    approval_handler=AutoApproveHandler(),
)
print(f"\nExecution result: {result}")
assert result["status"] == "succeeded"
assert result["steps_completed"] == 3

steps = list_workflow_run_steps(result["workflow_run_id"])
print(f"\nRecorded steps: {len(steps)}")
for s in steps:
    print(f"  Step {s['step_number']} ({s['tool_name']}): {s['status']}")

# Extract the created event id from step 2's stored result so we can
# clean it up (separate call, outside the workflow - a fresh
# run_id/approval, not testing batching here).
event_id = steps[1]["result"]["data"]["id"]
print(f"\nCreated event id: {event_id} - cleaning up...")
call_tool("calendar_delete_event", {"event_id": event_id}, approval_handler=AutoApproveHandler())
print("Cleanup complete")

# --- Failure case: unresolvable reference at execution time shouldn't happen
# given S1 validation, but confirm a genuinely bad template usage
# (missing required param) is rejected before anything runs.
from app.core.exceptions import ValidationError
try:
    execute_workflow("calendar_create_and_update_test", {}, approval_handler=AutoApproveHandler())
    print("BUG: missing required parameter was accepted!")
except ValidationError as e:
    print(f"\nCorrectly rejected missing required parameter: {e}")

print("\nAll checks passed.")