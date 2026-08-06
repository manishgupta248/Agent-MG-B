from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.job_queue import init_job_queue, enqueue_job, get_job, list_jobs, cancel_job
from app.core.exceptions import ValidationError
from app.registry.discovery import discover_tools

configure_logging()
init_db()
init_job_queue()
discover_tools()

# Enqueue a real READ tool - drive_search_files is registered and READ-permission.
job_id = enqueue_job("drive_search_files", {"query": "trashed = false", "max_results": 3})
print(f"Enqueued job {job_id}")

job = get_job(job_id)
print(f"Job status: {job['status']}, tool: {job['tool_name']}")

# Should be rejected: gmail_send_message is MODIFY permission.
try:
    enqueue_job("gmail_send_message", {"to": "x@example.com", "subject": "test", "body": "test"})
    print("BUG: MODIFY tool was accepted into the queue!")
except ValidationError as e:
    print(f"Correctly rejected MODIFY tool: {e}")

# Should be rejected: invalid input for a real READ tool (missing required field).
try:
    enqueue_job("drive_search_files", {"max_results": 3})  # missing required 'query'
    print("BUG: invalid input was accepted into the queue!")
except ValidationError as e:
    print(f"Correctly rejected invalid input: {e}")

# List and cancel
pending = list_jobs(status="pending")
print(f"\nPending jobs: {len(pending)}")

cancelled = cancel_job(job_id)
print(f"Cancelled job {job_id}: {cancelled}")

job = get_job(job_id)
print(f"Job status after cancel: {job['status']}")

# Cancelling again should return False (not already-pending)
cancelled_again = cancel_job(job_id)
print(f"Cancel already-cancelled job again: {cancelled_again} (should be False)")