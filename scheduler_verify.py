import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.scheduler import (
    init_scheduler, create_scheduled_task, get_scheduled_task, list_scheduled_tasks,
    get_due_tasks, mark_task_fired, set_task_enabled, delete_scheduled_task, DEFAULT_TIMEZONE,
)
from app.core.exceptions import ValidationError
from app.registry.discovery import discover_tools

configure_logging()
init_db()
init_scheduler()
discover_tools()

# Interval task - due in 2 seconds
interval_id = create_scheduled_task("calendar_list_events", {}, schedule_type="interval", interval_seconds=2)
print(f"Created interval task {interval_id}")

# One-time task - due in ~3 seconds (local Asia/Kolkata time)
soon = (datetime.now(ZoneInfo(DEFAULT_TIMEZONE)) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S")
one_time_id = create_scheduled_task("calendar_list_events", {}, schedule_type="one_time", run_at=soon)
print(f"Created one_time task {one_time_id} (run_at local: {soon})")

# Should be rejected: MODIFY tool
try:
    create_scheduled_task(
        "gmail_send_message", {"to": "x@example.com", "subject": "t", "body": "t"},
        schedule_type="interval", interval_seconds=60,
    )
    print("BUG: MODIFY tool was accepted!")
except ValidationError as e:
    print(f"Correctly rejected MODIFY tool: {e}")

# Should be rejected: one_time in the past
try:
    create_scheduled_task("calendar_list_events", {}, schedule_type="one_time", run_at="2020-01-01T00:00:00")
    print("BUG: past one_time task was accepted!")
except ValidationError as e:
    print(f"Correctly rejected past run_at: {e}")

print(f"\nNothing due yet: {get_due_tasks()}")

print("\nWaiting 4 seconds for both tasks to become due...")
time.sleep(4)

due_ids = [t["id"] for t in get_due_tasks()]
print(f"\nDue task ids: {due_ids}")
assert interval_id in due_ids, "interval task should be due"
assert one_time_id in due_ids, "one_time task should be due"

mark_task_fired(interval_id)
mark_task_fired(one_time_id)

interval_task = get_scheduled_task(interval_id)
one_time_task = get_scheduled_task(one_time_id)
print(f"\nInterval task after firing: enabled={interval_task['enabled']}, next_run_at={interval_task['next_run_at']}")
print(f"One-time task after firing: enabled={one_time_task['enabled']}")
assert interval_task["enabled"] is True, "interval task should still be enabled"
assert one_time_task["enabled"] is False, "one_time task should have auto-disabled"

set_task_enabled(interval_id, False)
print(f"\nAfter disabling interval task, due: {get_due_tasks()}")

delete_scheduled_task(interval_id)
delete_scheduled_task(one_time_id)
print(f"Remaining tasks: {list_scheduled_tasks()}")

print("\nAll checks passed.")