import time

from app.core.logging_setup import configure_logging
from app.core.database import init_db
from app.core.job_queue import init_job_queue, enqueue_job, get_job
from app.core.job_worker import start_background_worker, stop_background_worker
from app.registry.discovery import discover_tools

configure_logging()
init_db()
init_job_queue()
discover_tools()

start_background_worker()
print("Background worker started - enqueuing a job WITHOUT calling process_pending_jobs() manually...")

job_id = enqueue_job("calendar_list_events", {})
print(f"Enqueued job {job_id}")

# Poll interval is 10s - wait up to 20s for the background thread to
# claim and finish it on its own.
for _ in range(20):
    job = get_job(job_id)
    if job["status"] in ("succeeded", "failed"):
        break
    time.sleep(1)

job = get_job(job_id)
print(f"\nJob {job_id} final status: {job['status']}")
if job["status"] == "succeeded":
    print("Background worker picked up and completed the job automatically - correct.")
else:
    print(f"Unexpected outcome: {job}")

stop_background_worker()
print("Background worker stopped cleanly.")