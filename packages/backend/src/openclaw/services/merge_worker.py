"""Merge worker — executes queued merge jobs in the background.

Learn: When a task is approved, ReviewService.create_merge_job() inserts
a MergeJob(status=queued) row. This worker polls for queued jobs and
executes them:

  queued → running → success (merge_commit=<sha>) | failed (error=<msg>)

The actual git operations use the _run_git pattern from git_service.py.
On success, the task moves to "done". On failure, back to "in_progress".

This runs as a background task in the FastAPI lifespan, alongside the
dispatcher. It can also be started standalone for scaling.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import async_session_factory
from openclaw.db.models import MergeJob, Repository, Task
from openclaw.events.store import EventStore
from openclaw.events.types import MERGE_COMPLETED, MERGE_FAILED, MERGE_STARTED
from openclaw.observability.tracing import log_structured, new_span, new_trace

import logging as _logging

_trace_logger = _logging.getLogger("openclaw.services.merge_worker")
logger = structlog.get_logger()


# ─── Git helpers (local to merge worker) ────────────────────


async def _run_git(cwd: str, *args: str, timeout: float = 60.0):
    """Run a git command. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "Git command timed out"

    return (
        proc.returncode or 0,
        stdout.decode().strip(),
        stderr.decode().strip(),
    )


async def _get_merge_commit(repo_path: str) -> str:
    """Get the SHA of the current HEAD commit."""
    rc, stdout, _ = await _run_git(repo_path, "rev-parse", "HEAD")
    return stdout[:40] if rc == 0 else ""


# ─── Merge strategies ───────────────────────────────────────


async def _merge_rebase(repo_path: str, task_branch: str, target_branch: str) -> tuple[bool, str]:
    """Rebase task branch onto target, then fast-forward merge.

    Learn: This produces a linear history. Steps:
    1. Checkout task branch
    2. Rebase onto target
    3. Checkout target
    4. Fast-forward merge
    """
    # Checkout task branch
    rc, _, err = await _run_git(repo_path, "checkout", task_branch)
    if rc != 0:
        return False, f"checkout {task_branch}: {err}"

    # Rebase onto target
    rc, _, err = await _run_git(repo_path, "rebase", target_branch)
    if rc != 0:
        await _run_git(repo_path, "rebase", "--abort")
        return False, f"rebase onto {target_branch}: {err}"

    # Checkout target and fast-forward
    rc, _, err = await _run_git(repo_path, "checkout", target_branch)
    if rc != 0:
        return False, f"checkout {target_branch}: {err}"

    rc, _, err = await _run_git(repo_path, "merge", "--ff-only", task_branch)
    if rc != 0:
        return False, f"fast-forward merge: {err}"

    return True, ""


async def _merge_regular(repo_path: str, task_branch: str, target_branch: str) -> tuple[bool, str]:
    """Standard merge with a merge commit."""
    rc, _, err = await _run_git(repo_path, "checkout", target_branch)
    if rc != 0:
        return False, f"checkout {target_branch}: {err}"

    rc, _, err = await _run_git(
        repo_path, "merge", "--no-ff",
        "-m", f"Merge branch '{task_branch}' into {target_branch}",
        task_branch,
    )
    if rc != 0:
        await _run_git(repo_path, "merge", "--abort")
        return False, f"merge: {err}"

    return True, ""


async def _merge_squash(repo_path: str, task_branch: str, target_branch: str) -> tuple[bool, str]:
    """Squash merge — all commits collapsed into one."""
    rc, _, err = await _run_git(repo_path, "checkout", target_branch)
    if rc != 0:
        return False, f"checkout {target_branch}: {err}"

    rc, _, err = await _run_git(repo_path, "merge", "--squash", task_branch)
    if rc != 0:
        await _run_git(repo_path, "merge", "--abort")
        return False, f"squash merge: {err}"

    rc, _, err = await _run_git(
        repo_path, "commit",
        "-m", f"Squash merge: {task_branch}",
    )
    if rc != 0:
        return False, f"squash commit: {err}"

    return True, ""


_STRATEGIES = {
    "rebase": _merge_rebase,
    "merge": _merge_regular,
    "squash": _merge_squash,
}


# ─── Worker ─────────────────────────────────────────────────


async def _execute_merge_job(db: AsyncSession, job: MergeJob) -> None:
    """Execute a single merge job.

    Learn: This is the core logic — load task+repo, run git merge,
    update statuses. All wrapped in proper error handling.
    """
    events = EventStore(db)
    log = logger.bind(merge_job_id=job.id, task_id=job.task_id)

    # Trace merge operation
    new_trace()
    new_span("merge.execute")
    log_structured(
        _trace_logger, _logging.INFO, "merge.job.started",
        merge_job_id=job.id, task_id=job.task_id, strategy=job.strategy,
    )

    # Mark as running
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await db.commit()

    await events.append(
        stream_id=f"task:{job.task_id}",
        event_type=MERGE_STARTED,
        data={"merge_job_id": job.id, "task_id": job.task_id, "strategy": job.strategy},
    )
    await db.commit()

    log.info("merge.started", strategy=job.strategy)

    # Load task and repo
    task = await db.get(Task, job.task_id)
    repo = await db.get(Repository, job.repo_id)

    if not task or not repo:
        job.status = "failed"
        job.error = "Task or repository not found"
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()
        log.error("merge.failed", error=job.error)
        return

    # Get the merge strategy function
    strategy_fn = _STRATEGIES.get(job.strategy)
    if not strategy_fn:
        job.status = "failed"
        job.error = f"Unknown merge strategy: {job.strategy}"
        job.completed_at = datetime.now(timezone.utc)
        await db.commit()
        log.error("merge.failed", error=job.error)
        return

    # Execute the merge
    task_branch = task.branch
    target_branch = repo.default_branch

    try:
        success, error_msg = await strategy_fn(repo.local_path, task_branch, target_branch)
    except Exception as e:
        success = False
        error_msg = str(e)

    if success:
        # Get merge commit SHA
        merge_commit = await _get_merge_commit(repo.local_path)

        job.status = "success"
        job.merge_commit = merge_commit
        job.completed_at = datetime.now(timezone.utc)

        # Move task to done
        task.status = "done"
        task.completed_at = datetime.now(timezone.utc)

        await events.append(
            stream_id=f"task:{job.task_id}",
            event_type=MERGE_COMPLETED,
            data={
                "merge_job_id": job.id,
                "task_id": job.task_id,
                "merge_commit": merge_commit,
                "strategy": job.strategy,
            },
        )
        await db.commit()
        log.info("merge.completed", merge_commit=merge_commit)

    else:
        job.status = "failed"
        job.error = error_msg
        job.completed_at = datetime.now(timezone.utc)

        # Move task back to in_progress so it can be fixed and re-queued
        task.status = "in_progress"

        await events.append(
            stream_id=f"task:{job.task_id}",
            event_type=MERGE_FAILED,
            data={
                "merge_job_id": job.id,
                "task_id": job.task_id,
                "error": error_msg,
                "strategy": job.strategy,
            },
        )
        await db.commit()
        log.warning("merge.failed", error=error_msg)


class MergeWorker:
    """Background worker that processes queued merge jobs.

    Learn: Runs as a long-lived task in the FastAPI lifespan. Polls
    the merge_jobs table for queued jobs. Each job gets its own
    DB session for transaction isolation.

    Usage:
        worker = MergeWorker()
        asyncio.create_task(worker.run_loop())
    """

    def __init__(self, poll_interval: float = 5.0):
        self.poll_interval = poll_interval
        self._running = False

    async def run_loop(self) -> None:
        """Main worker loop — poll for queued jobs and execute them."""
        self._running = True
        logger.info("merge_worker.started", poll_interval=self.poll_interval)

        while self._running:
            try:
                await self._process_one()
            except Exception:
                logger.exception("merge_worker.error")
            await asyncio.sleep(self.poll_interval)

    async def _process_one(self) -> None:
        """Claim and execute the next queued merge job (if any)."""
        async with async_session_factory() as db:
            # Find oldest queued job
            q = (
                select(MergeJob)
                .where(MergeJob.status == "queued")
                .order_by(MergeJob.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)  # Skip if another worker has it
            )
            result = await db.execute(q)
            job = result.scalars().first()

            if not job:
                return  # Nothing to do

            await _execute_merge_job(db, job)

    def stop(self) -> None:
        """Signal the worker to stop."""
        self._running = False
        logger.info("merge_worker.stopping")
