"""
Job Queue worker (M10-S2): executes 'pending' jobs via a bounded
ThreadPoolExecutor.

Scope for this step: manual trigger only (process_pending_jobs()) - no
background polling thread yet. Whatever calls this (main.py, a future
Telegram command, or the Scheduler in M11) decides WHEN jobs run; the
worker itself has no opinion about timing.

Concurrency notes:
- Fixed pool size (POOL_SIZE), not configurable via Settings yet -
  conservative default for an 8GB RAM machine also running the
  Telegram bot. Revisit if job volume ever justifies tuning this.
- Claiming happens SEQUENTIALLY on the calling thread, one job at a
  time, BEFORE any thread pool submission - never inside a worker
  thread. This sidesteps a claim race entirely within a single
  process_pending_jobs() call: only one thread is ever deciding "is
  this job still pending" and flipping it to 'running'. Known
  limitation: two concurrent process_pending_jobs() calls (e.g. two
  different triggers firing at once) could still race on claiming the
  SAME job - not handled here, not expected to matter until something
  actually calls this concurrently, which is out of scope until the
  Scheduler (M11) exists.
- Each worker thread invokes call_tool() with NO approval_handler.
  Only safe because enqueue_job() (M10-S1) guarantees every queued
  tool is READ-permission, and APPROVAL_POLICY[READ] = False - so
  call_tool never reaches its "approval required but no handler"
  branch for a job-sourced call. If that invariant is ever broken (a
  MODIFY tool enters the table some other way), call_tool raises
  ToolExecutionError rather than silently skipping approval - fail
  loudly, not fail open.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from app.core.call_tool import call_tool
from app.core.event_bus import publish
from app.core.exceptions import ToolExecutionError, ValidationError
from app.core.job_queue import claim_job, complete_job, fail_job, get_job, list_jobs
import threading
POOL_SIZE = 3


def _run_job(job: dict) -> None:
    """
    Executes a single already-claimed job and writes the outcome back
    to the jobs table. Runs on a worker thread - deliberately catches
    the tool's own failure modes (ToolExecutionError, ValidationError)
    so the jobs table always reflects an outcome, but does NOT swallow
    unexpected exception types, so a real bug in this function itself
    still surfaces loudly to the caller via the future.
    """
    job_id = job["id"]
    tool_name = job["tool_name"]

    publish("job.started", {"job_id": job_id, "tool_name": tool_name})
    logger.info(f"Job {job_id} started ({tool_name})")

    try:
        result = call_tool(tool_name, job["input"], run_id=job["run_id"])
    except (ToolExecutionError, ValidationError) as e:
        # Expected failure modes from call_tool - the tool call itself
        # failing, not a worker bug. Caught separately from a bare
        # Exception so an unexpected error type still propagates.
        error_message = str(e)
        fail_job(job_id, error_message)
        publish("job.failed", {"job_id": job_id, "tool_name": tool_name, "error": error_message})
        logger.error(f"Job {job_id} failed: {error_message}")
        return

    complete_job(job_id, result.model_dump())
    publish("job.succeeded", {"job_id": job_id, "tool_name": tool_name})
    logger.info(f"Job {job_id} succeeded")


def process_pending_jobs(max_jobs: int | None = None) -> dict:
    """
    Claims and executes all currently-pending jobs (or up to max_jobs),
    using a bounded thread pool. Blocks until every claimed job has
    finished (success or failure) before returning.

    Returns {"claimed": N, "succeeded": N, "failed": N}. A job that
    loses a claim race (already grabbed between listing and claiming)
    is simply skipped, not counted as a failure - "not our job to run"
    isn't the same thing as the job itself failing.
    """
    pending = list_jobs(status="pending")
    if max_jobs is not None:
        pending = pending[:max_jobs]

    claimed_jobs = [job for job in pending if claim_job(job["id"])]

    if not claimed_jobs:
        logger.debug("No pending jobs to process")
        return {"claimed": 0, "succeeded": 0, "failed": 0}

    logger.info(f"Claimed {len(claimed_jobs)} job(s), dispatching to {POOL_SIZE}-thread pool")

    with ThreadPoolExecutor(max_workers=POOL_SIZE) as executor:
        futures = {executor.submit(_run_job, job): job["id"] for job in claimed_jobs}
        for future in as_completed(futures):
            job_id = futures[future]
            try:
                future.result()  # re-raises only if _run_job itself raised unexpectedly
            except Exception as e:
                # _run_job raised something it wasn't supposed to - a
                # real worker-level bug, not a normal tool failure
                # (those are caught inside _run_job already). The
                # job's row may be left in 'running' - itself a useful
                # signal something went wrong at the worker level.
                logger.error(f"Job {job_id} worker thread raised unexpectedly: {e}")

    succeeded = failed = 0
    for job in claimed_jobs:
        final = get_job(job["id"])
        if final["status"] == "succeeded":
            succeeded += 1
        elif final["status"] == "failed":
            failed += 1

    summary = {"claimed": len(claimed_jobs), "succeeded": succeeded, "failed": failed}
    logger.info(f"process_pending_jobs complete: {summary}")
    return summary

# Background polling - M10-S3. Fixed interval, not configurable via
# Settings for now (kept simple per scoping decision).
POLL_INTERVAL_SECONDS = 10

_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def _poll_loop() -> None:
    """
    Runs on a dedicated daemon thread, calling process_pending_jobs()
    every POLL_INTERVAL_SECONDS until stop_background_worker() is
    called. Uses _stop_event.wait(timeout) rather than time.sleep() so
    a stop request is honored within the wait, not after a full sleep
    interval elapses.

    Deliberately intended to be the ONLY caller of process_pending_jobs()
    once running - see that function's own docstring on concurrent
    callers racing on job claims. If something else (e.g. a future
    Telegram "run jobs now" command) also calls it while this loop is
    active, that known limitation applies; not handled here.
    """
    logger.info(f"Job worker background polling started (interval={POLL_INTERVAL_SECONDS}s)")
    while not _stop_event.is_set():
        try:
            process_pending_jobs()
        except Exception as e:
            # The polling loop itself must never die from an unexpected
            # error - a silently-dead background thread would stop all
            # future job processing with no visible symptom until
            # someone notices jobs piling up as 'pending'.
            logger.error(f"Job worker poll cycle raised unexpectedly: {e}")
        _stop_event.wait(POLL_INTERVAL_SECONDS)
    logger.info("Job worker background polling stopped")


def start_background_worker() -> None:
    """
    Starts the polling loop on a daemon thread. daemon=True so this
    thread never blocks process exit - a background chore should never
    prevent shutdown.

    Safe to call once during bootstrap(). Calling it twice would start
    a second polling thread running concurrently with the first - not
    guarded against here since nothing in the current boot sequence
    calls it more than once; worth revisiting if that assumption ever
    changes.
    """
    global _worker_thread
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_poll_loop, daemon=True, name="job-worker-poll")
    _worker_thread.start()


def stop_background_worker(timeout: float = 15.0) -> None:
    """
    Signals the polling loop to stop and waits up to `timeout` seconds
    for it to actually exit. Mainly useful for scratch scripts/tests
    that need a clean, deterministic shutdown rather than relying on
    daemon-thread-dies-with-process behavior.
    """
    _stop_event.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=timeout)