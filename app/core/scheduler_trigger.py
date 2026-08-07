"""
Scheduler trigger logic (M11-S2): finds due scheduled tasks and
enqueues them into the Job Queue (M10). The Scheduler decides WHEN;
the Job Queue's existing worker (M10-S2/S3) decides HOW a fired task
actually executes - this module is the bridge between the two.

Scope for this step: manual trigger only (check_due_tasks() called
explicitly). Background polling is M11-S3, mirroring the Job Queue's
own S2(worker)/S3(background polling) split.
"""

from loguru import logger

from app.core.event_bus import publish
from app.core.job_queue import enqueue_job
from app.core.scheduler import get_due_tasks, mark_task_fired


def check_due_tasks() -> dict:
    """
    Finds all currently-due enabled scheduled tasks and enqueues each
    as a Job Queue job. Every due task is marked fired afterward
    regardless of whether enqueueing succeeded - see module docstring
    on why enqueue failures aren't left for retry.

    run_id is set to f"scheduled-task-{task_id}" for each enqueued job,
    so execution_history/job rows are traceable back to the scheduled
    task that created them.

    Returns {"checked": N, "enqueued": N, "failed": N}.
    """
    due = get_due_tasks()
    enqueued = failed = 0

    for task in due:
        run_id = f"scheduled-task-{task['id']}"
        try:
            job_id = enqueue_job(task["tool_name"], task["input"], run_id=run_id)
            logger.info(f"Scheduled task {task['id']} fired -> enqueued job {job_id}")
            publish("scheduled_task.fired", {
                "task_id": task["id"], "tool_name": task["tool_name"], "job_id": job_id,
            })
            enqueued += 1
        except Exception as e:
            # Deliberately broad: enqueue_job can raise ValidationError
            # for several reasons (tool unregistered, input_schema
            # changed since the task was created, etc.) - any of them
            # means this occurrence can't run, and per the module
            # docstring we mark it fired rather than retry forever.
            logger.error(f"Scheduled task {task['id']} failed to enqueue: {e}")
            publish("scheduled_task.enqueue_failed", {"task_id": task["id"], "error": str(e)})
            failed += 1
        finally:
            mark_task_fired(task["id"])

    result = {"checked": len(due), "enqueued": enqueued, "failed": failed}
    if due:
        logger.info(f"check_due_tasks complete: {result}")
    else:
        logger.debug("No due scheduled tasks")
    return result