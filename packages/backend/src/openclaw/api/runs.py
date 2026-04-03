"""Run API routes.

CRUD + state machine transitions for runs, run tasks, and budget.
Planning and execution are kicked off as background tasks.
"""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import get_db
from openclaw.db.models import Repository, Run
from openclaw.schemas.run import (
    BudgetEntryRead,
    BudgetLedgerRead,
    ContractLock,
    ContractRead,
    RunCreate,
    RunRead,
    RunTaskRead,
    PlanApproval,
    PlanRejection,
)
from openclaw.services.contract_builder import ContractBuilder
from openclaw.services.execution_loop import ExecutionLoop
from openclaw.services.run_budget_service import RunBudgetService
from openclaw.services.run_service import (
    InvalidRunTransitionError,
    RunService,
)
from openclaw.services.planner_service import PlannerService

router = APIRouter()


# ─── Service factories ────────────────────────────────────


def _svc(db: AsyncSession = Depends(get_db)) -> RunService:
    return RunService(db)


def _budget_svc(db: AsyncSession = Depends(get_db)) -> RunBudgetService:
    return RunBudgetService(db)


# ─── Run CRUD ────────────────────────────────────────


@router.post(
    "/teams/{team_id}/runs",
    response_model=RunRead,
    status_code=201,
)
async def create_run(
    team_id: uuid.UUID,
    body: RunCreate,
    svc: RunService = Depends(_svc),
):
    """Create a new run in draft status."""
    try:
        # Use template budget if specified and no explicit budget override
        budget = body.budget_limit_usd
        if body.template:
            from openclaw.services.planner_service import RUN_TEMPLATES
            tmpl = RUN_TEMPLATES.get(body.template)
            if tmpl and budget == 10.0:  # default budget → use template's
                budget = float(tmpl["budget"])

        run = await svc.create_run(
            team_id=team_id,
            title=body.title,
            intent=body.intent,
            budget_limit=budget,
            repository_id=body.repository_id,
        )

        # Store template in metadata if specified
        if body.template:
            run.run_metadata = {
                **(run.run_metadata or {}),
                "template": body.template,
            }
            await svc.db.commit()

        return run
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/teams/{team_id}/runs",
    response_model=list[RunRead],
)
async def list_runs(
    team_id: uuid.UUID,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    svc: RunService = Depends(_svc),
):
    """List runs for a team, optionally filtered by status."""
    return await svc.list_runs(
        team_id=team_id, status=status, limit=limit, offset=offset
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunRead,
)
async def get_run(
    run_id: uuid.UUID,
    svc: RunService = Depends(_svc),
):
    """Get run detail."""
    run = await svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ─── Planning ─────────────────────────────────────────────


@router.post(
    "/runs/{run_id}/start",
    response_model=RunRead,
)
async def start_run(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start planning for a run — kicks off LLM planner in background."""
    svc = RunService(db)
    run = await svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Run must be in 'draft' status to start planning, got '{run.status}'",
        )

    async def _plan():
        from openclaw.db.engine import async_session_factory

        async with async_session_factory() as plan_db:
            planner = PlannerService(plan_db, session_factory=async_session_factory)
            await planner.plan(run_id)

    background_tasks.add_task(_plan)
    return run


# ─── Run Tasks ───────────────────────────────────────


@router.get(
    "/runs/{run_id}/tasks",
    response_model=list[RunTaskRead],
)
async def list_run_tasks(
    run_id: uuid.UUID,
    svc: RunService = Depends(_svc),
):
    """List tasks within a run."""
    return await svc.list_run_tasks(run_id)


# ─── Status transitions ──────────────────────────────────


from pydantic import BaseModel


class RunStatusChange(BaseModel):
    status: str
    actor_id: Optional[uuid.UUID] = None


@router.post(
    "/runs/{run_id}/status",
    response_model=RunRead,
)
async def change_run_status(
    run_id: uuid.UUID,
    body: RunStatusChange,
    svc: RunService = Depends(_svc),
):
    """Transition run to a new status."""
    try:
        return await svc.change_status(run_id, body.status, body.actor_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRunTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/runs/{run_id}/approve-plan",
    response_model=RunRead,
)
async def approve_plan(
    run_id: uuid.UUID,
    body: PlanApproval,
    background_tasks: BackgroundTasks,
    svc: RunService = Depends(_svc),
):
    """Approve the generated plan — starts execution in background."""
    try:
        run = await svc.approve_plan(run_id, body.actor_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRunTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Kick off the execution loop as a background task
    loop = ExecutionLoop()
    background_tasks.add_task(loop.run, run_id)
    return run


@router.post(
    "/runs/{run_id}/reject-plan",
    response_model=RunRead,
)
async def reject_plan(
    run_id: uuid.UUID,
    body: PlanRejection,
    svc: RunService = Depends(_svc),
):
    """Reject the generated plan with optional feedback."""
    try:
        return await svc.reject_plan(run_id, body.actor_id, body.feedback)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRunTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/runs/{run_id}/pause",
    response_model=RunRead,
)
async def pause_run(
    run_id: uuid.UUID,
    svc: RunService = Depends(_svc),
):
    """Pause an executing run."""
    try:
        return await svc.change_status(run_id, "paused")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRunTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunRead,
)
async def resume_run(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    svc: RunService = Depends(_svc),
):
    """Resume a paused or crashed run via ExecutionLoop.resume().

    Resets interrupted tasks and continues execution in background.
    """
    try:
        loop = ExecutionLoop()

        # Validate run exists before background dispatch
        run = await svc.db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        background_tasks.add_task(loop.resume, run_id)

        # Re-read after potential status change
        await svc.db.refresh(run)
        return run
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRunTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ─── Task Graph ───────────────────────────────────────────


class TaskGraphBody(BaseModel):
    task_graph: dict


@router.post(
    "/runs/{run_id}/task-graph",
    response_model=RunRead,
)
async def set_task_graph(
    run_id: uuid.UUID,
    body: TaskGraphBody,
    svc: RunService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    """Store the task graph (from planner agent or manual input).

    If the run is in 'planning' status, auto-transitions to
    'awaiting_plan_approval' after storing the task graph.
    """
    try:
        run = await svc.set_task_graph(run_id, body.task_graph)

        # Auto-transition if called during planning phase
        if run.status == "planning":
            run = await svc.change_status(run_id, "awaiting_plan_approval")

        return run
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Diff & Merge ─────────────────────────────────────────


class RunMergeRequest(BaseModel):
    strategy: str = "merge"
    create_pr: bool = False


@router.get("/runs/{run_id}/diff")
async def get_run_diff(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get combined diff: feature branch vs main."""
    from openclaw.services.git_service import GitService

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.repository_id or not run.branch_name:
        raise HTTPException(
            status_code=400,
            detail="Run has no repository or branch. Register a repo first.",
        )

    repo = await db.get(Repository, run.repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    git_svc = GitService(db)
    diff = await git_svc.get_branch_diff(
        run.branch_name, repo.default_branch, run.repository_id,
    )
    changed_files = await git_svc.get_branch_changed_files(
        run.branch_name, repo.default_branch, run.repository_id,
    )
    return {
        "diff": diff,
        "files": [
            {"path": f.path, "status": f.status,
             "additions": f.additions, "deletions": f.deletions}
            for f in changed_files
        ],
        "branch": run.branch_name,
        "base": repo.default_branch,
    }


@router.post("/runs/{run_id}/merge")
async def merge_run(
    run_id: uuid.UUID,
    body: RunMergeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Merge feature branch into main (or create PR)."""
    from openclaw.services.git_service import GitService

    svc = RunService(db)
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "reviewing":
        raise HTTPException(
            status_code=409,
            detail=f"Run must be in 'reviewing' status, got '{run.status}'",
        )
    if not run.repository_id or not run.branch_name:
        raise HTTPException(
            status_code=400, detail="Run has no repository or branch",
        )

    repo = await db.get(Repository, run.repository_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    git_svc = GitService(db)

    if body.create_pr:
        # Push feature branch
        push_result = await git_svc.push_branch_by_name(
            run.branch_name, run.repository_id,
        )
        if not push_result.ok:
            raise HTTPException(
                status_code=500,
                detail=f"Push failed: {push_result.stderr}",
            )

        # Create PR via gh CLI
        import shutil
        if not shutil.which("gh"):
            raise HTTPException(
                status_code=500,
                detail="gh CLI not installed — install from https://cli.github.com",
            )

        pr_proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "create",
            "--title", run.title,
            "--body", f"Created by Entourage run {str(run_id)[:8]}\n\n{run.intent or ''}",
            "--base", repo.default_branch,
            "--head", run.branch_name,
            cwd=repo.local_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pr_stdout, pr_stderr = await asyncio.wait_for(
            pr_proc.communicate(), timeout=30.0,
        )
        pr_result_ok = pr_proc.returncode == 0
        pr_result_stdout = pr_stdout.decode().strip() if pr_stdout else ""
        pr_result_stderr = pr_stderr.decode().strip() if pr_stderr else ""

        if pr_result_ok:
            pr_url = pr_result_stdout
            run.pr_url = pr_url
            await db.commit()
            await svc.change_status(run_id, "merging")
            return {"status": "pr_created", "pr_url": pr_url, "branch": run.branch_name}
        else:
            await svc.change_status(run_id, "merging")
            return {
                "status": "pr_failed",
                "error": pr_result_stderr,
                "branch": run.branch_name,
            }
    else:
        # Direct merge to main
        merge_result = await git_svc.merge_branch(
            source_branch=run.branch_name,
            target_branch=repo.default_branch,
            repo_id=run.repository_id,
            strategy=body.strategy,
        )
        if merge_result.ok:
            await svc.change_status(run_id, "done")
            return {"status": "merged", "branch": run.branch_name}
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Merge failed: {merge_result.stderr}",
            )


# ─── Contracts ────────────────────────────────────────────


@router.get(
    "/runs/{run_id}/contracts",
    response_model=list[ContractRead],
)
async def list_contracts(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all contracts for a run."""
    builder = ContractBuilder(db)
    return await builder.get_contracts(run_id)


@router.get(
    "/runs/{run_id}/contracts/{contract_id}",
    response_model=ContractRead,
)
async def get_contract(
    run_id: uuid.UUID,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific contract by ID."""
    builder = ContractBuilder(db)
    contract = await builder.get_contract(contract_id)
    if not contract or contract.run_id != run_id:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.post(
    "/runs/{run_id}/contracts/{contract_id}/lock",
    response_model=ContractRead,
)
async def lock_contract(
    run_id: uuid.UUID,
    contract_id: int,
    body: ContractLock,
    db: AsyncSession = Depends(get_db),
):
    """Agent acknowledges a contract before starting work."""
    builder = ContractBuilder(db)
    try:
        return await builder.lock_contract(contract_id, body.agent_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/runs/{run_id}/generate-contracts",
    response_model=RunRead,
)
async def generate_contracts(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger contract generation from the task graph — runs in background."""
    svc = RunService(db)
    run = await svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def _generate():
        from openclaw.db.engine import async_session_factory

        async with async_session_factory() as gen_db:
            builder = ContractBuilder(gen_db)
            await builder.generate_contracts(run_id)

    background_tasks.add_task(_generate)
    return run


# ─── Budget ───────────────────────────────────────────────


@router.get(
    "/runs/{run_id}/budget",
    response_model=BudgetLedgerRead,
)
async def get_run_budget(
    run_id: uuid.UUID,
    budget_svc: RunBudgetService = Depends(_budget_svc),
):
    """Get the budget ledger for a run."""
    ledger = await budget_svc.get_ledger(run_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="Budget ledger not found")
    return ledger


@router.get(
    "/runs/{run_id}/budget/entries",
    response_model=list[BudgetEntryRead],
)
async def list_budget_entries(
    run_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    budget_svc: RunBudgetService = Depends(_budget_svc),
):
    """List cost entries for a run."""
    return await budget_svc.list_entries(run_id, limit=limit)
