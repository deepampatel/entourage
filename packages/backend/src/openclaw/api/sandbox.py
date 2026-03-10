"""Sandbox API routes — trigger and query Docker-based test runs.

Learn: These routes let agents (via MCP) and humans (via dashboard)
trigger sandboxed test runs for run tasks and query results.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.config import settings
from openclaw.db.engine import get_db
from openclaw.db.models import Run, RunTask, Repository, SandboxRun
from openclaw.schemas.sandbox import SandboxRunCreate, SandboxRunRead
from openclaw.services.sandbox_manager import SandboxManager

router = APIRouter()

_sandbox_mgr = SandboxManager()


async def _persist_sandbox_result(
    db_factory,
    sandbox_run_id: int,
    result,
) -> None:
    """Background task: update SandboxRun row with execution result."""
    from openclaw.db.engine import async_session_factory

    async with async_session_factory() as db:
        run = await db.get(SandboxRun, sandbox_run_id)
        if run:
            run.exit_code = result.exit_code
            run.stdout = result.stdout
            run.stderr = result.stderr
            run.passed = result.passed
            run.duration_seconds = result.duration_seconds
            run.ended_at = result.ended_at
            await db.commit()


async def _run_sandbox_background(
    sandbox_run_id: int,
    worktree_path: str,
    test_cmd: str,
    image: str,
    setup_cmd: str | None,
    timeout: int,
) -> None:
    """Background task: run sandbox tests and persist results."""
    from openclaw.db.engine import async_session_factory

    result = await _sandbox_mgr.run_tests(
        worktree_path=worktree_path,
        test_cmd=test_cmd,
        image=image,
        setup_cmd=setup_cmd,
        timeout=timeout,
    )
    await _persist_sandbox_result(None, sandbox_run_id, result)


# ─── Endpoints ──────────────────────────────────────────


@router.get(
    "/runs/{run_id}/tasks/{task_id}/sandbox-runs",
    response_model=list[SandboxRunRead],
)
async def list_sandbox_runs(
    run_id: uuid.UUID,
    task_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List sandbox runs for a run task."""
    result = await db.execute(
        select(SandboxRun)
        .where(
            SandboxRun.run_id == run_id,
            SandboxRun.run_task_id == task_id,
        )
        .order_by(SandboxRun.started_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post(
    "/runs/{run_id}/tasks/{task_id}/sandbox-runs",
    response_model=SandboxRunRead,
    status_code=202,
)
async def trigger_sandbox_run(
    run_id: uuid.UUID,
    task_id: int,
    body: SandboxRunCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a sandbox test run for a run task (async, returns 202)."""
    # Validate run and task exist
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    ptask_result = await db.execute(
        select(RunTask).where(
            RunTask.id == task_id,
            RunTask.run_id == run_id,
        )
    )
    ptask = ptask_result.scalars().first()
    if not ptask:
        raise HTTPException(status_code=404, detail="Run task not found")

    # Check sandbox availability
    if not settings.sandbox_enabled:
        raise HTTPException(status_code=503, detail="Sandbox testing is disabled")

    docker_available = await _sandbox_mgr.check_docker()
    if not docker_available:
        raise HTTPException(
            status_code=503, detail="Docker is not available for sandbox testing"
        )

    # Determine worktree path from repository
    worktree_path = "/workspace"
    if run.repository_id:
        repo = await db.get(Repository, run.repository_id)
        if repo:
            worktree_path = repo.local_path

    # Create SandboxRun row
    import uuid as _uuid

    sandbox_id = _uuid.uuid4().hex[:12]
    run = SandboxRun(
        sandbox_id=sandbox_id,
        run_id=run_id,
        run_task_id=task_id,
        team_id=run.team_id,
        test_cmd=body.test_cmd,
        image=body.image,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Launch background test execution
    background_tasks.add_task(
        _run_sandbox_background,
        sandbox_run_id=run.id,
        worktree_path=worktree_path,
        test_cmd=body.test_cmd,
        image=body.image,
        setup_cmd=body.setup_cmd,
        timeout=body.timeout,
    )

    return run


@router.get("/sandbox-runs/{sandbox_id}", response_model=SandboxRunRead)
async def get_sandbox_run(
    sandbox_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific sandbox run by its sandbox_id."""
    result = await db.execute(
        select(SandboxRun).where(SandboxRun.sandbox_id == sandbox_id)
    )
    run = result.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Sandbox run not found")
    return run
