import time

from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.job_queue import init_job_queue, list_jobs
from app.core.scheduler import init_scheduler, create_scheduled_task, get_scheduled_task
from app.core.scheduler_trigger import check_due_tasks
from app.registry.discovery import discover_tools

configure_logging()
init_db()
init_job_queue()
init_scheduler()
discover_tools()

# Interval task due in 1 second.
task_id = create_scheduled_task("calendar_list_events", {}, schedule_type="interval", interval_seconds=1)
print(f"Created scheduled task {task_id}")

# Nothing due yet - confirm check_due_tasks() is a no-op right now.
result = check_due_tasks()
print(f"\nImmediate check (should be empty): {result}")
assert result == {"checked": 0, "enqueued": 0, "failed": 0}

print("\nWaiting 2 seconds for the task to become due...")
time.sleep(2)

result = check_due_tasks()
print(f"\nCheck after wait: {result}")
assert result["checked"] == 1 and result["enqueued"] == 1 and result["failed"] == 0

# Confirm a real job landed in the Job Queue, tagged with the expected run_id.
expected_run_id = f"scheduled-task-{task_id}"
matching_jobs = [j for j in list_jobs() if j["run_id"] == expected_run_id]
print(f"\nJobs with run_id='{expected_run_id}': {len(matching_jobs)}")
assert len(matching_jobs) == 1
print(f"Job: {matching_jobs[0]['tool_name']}, status={matching_jobs[0]['status']}")

# Confirm the task itself advanced (interval task, should still be enabled).
task = get_scheduled_task(task_id)
print(f"\nTask after firing: enabled={task['enabled']}, last_run_at={task['last_run_at']}, next_run_at={task['next_run_at']}")
assert task["enabled"] is True
assert task["last_run_at"] is not None

print("\nAll checks passed.")