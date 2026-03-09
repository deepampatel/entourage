"""Pipeline API routes.

CRUD + state machine transitions for pipelines, pipeline tasks, and budget.
Planning and execution are kicked off as background tasks.
"""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import get_db
from openclaw.schemas.pipeline import (
    BudgetEntryRead,
    BudgetLedgerRead,
    ContractLock,
    ContractRead,
    PipelineCreate,
    PipelineRead,
    PipelineTaskRead,
    PlanApproval,
    PlanRejection,
)
from openclaw.services.contract_builder import ContractBuilder
from openclaw.services.execution_loop import ExecutionLoop
from openclaw.services.pipeline_budget_service import PipelineBudgetService
from openclaw.services.pipeline_service import (
    InvalidPipelineTransitionError,
    PipelineService,
)
from openclaw.services.planner_service import PlannerService

router = APIRouter()


# ─── Service factories ────────────────────────────────────


def _svc(db: AsyncSession = Depends(get_db)) -> PipelineService:
    return PipelineService(db)


def _budget_svc(db: AsyncSession = Depends(get_db)) -> PipelineBudgetService:
    return PipelineBudgetService(db)


# ─── Pipeline CRUD ────────────────────────────────────────


@router.post(
    "/teams/{team_id}/pipelines",
    response_model=PipelineRead,
    status_code=201,
)
async def create_pipeline(
    team_id: uuid.UUID,
    body: PipelineCreate,
    svc: PipelineService = Depends(_svc),
):
    """Create a new pipeline in draft status."""
    try:
        pipeline = await svc.create_pipeline(
            team_id=team_id,
            title=body.title,
            intent=body.intent,
            budget_limit=body.budget_limit_usd,
            repository_id=body.repository_id,
        )
        return pipeline
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/teams/{team_id}/pipelines",
    response_model=list[PipelineRead],
)
async def list_pipelines(
    team_id: uuid.UUID,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    svc: PipelineService = Depends(_svc),
):
    """List pipelines for a team, optionally filtered by status."""
    return await svc.list_pipelines(
        team_id=team_id, status=status, limit=limit, offset=offset
    )


@router.get(
    "/pipelines/{pipeline_id}",
    response_model=PipelineRead,
)
async def get_pipeline(
    pipeline_id: uuid.UUID,
    svc: PipelineService = Depends(_svc),
):
    """Get pipeline detail."""
    pipeline = await svc.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


# ─── Planning ─────────────────────────────────────────────


@router.post(
    "/pipelines/{pipeline_id}/start",
    response_model=PipelineRead,
)
async def start_pipeline(
    pipeline_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start planning for a pipeline — kicks off LLM planner in background."""
    svc = PipelineService(db)
    pipeline = await svc.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if pipeline.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline must be in 'draft' status to start planning, got '{pipeline.status}'",
        )

    async def _plan():
        from openclaw.db.engine import async_session_factory

        async with async_session_factory() as plan_db:
            planner = PlannerService(plan_db)
            await planner.plan(pipeline_id)

    background_tasks.add_task(_plan)
    return pipeline


# ─── Pipeline Tasks ───────────────────────────────────────


@router.get(
    "/pipelines/{pipeline_id}/tasks",
    response_model=list[PipelineTaskRead],
)
async def list_pipeline_tasks(
    pipeline_id: uuid.UUID,
    svc: PipelineService = Depends(_svc),
):
    """List tasks within a pipeline."""
    return await svc.list_pipeline_tasks(pipeline_id)


# ─── Status transitions ──────────────────────────────────


from pydantic import BaseModel


class PipelineStatusChange(BaseModel):
    status: str
    actor_id: Optional[uuid.UUID] = None


@router.post(
    "/pipelines/{pipeline_id}/status",
    response_model=PipelineRead,
)
async def change_pipeline_status(
    pipeline_id: uuid.UUID,
    body: PipelineStatusChange,
    svc: PipelineService = Depends(_svc),
):
    """Transition pipeline to a new status."""
    try:
        return await svc.change_status(pipeline_id, body.status, body.actor_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidPipelineTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/pipelines/{pipeline_id}/approve-plan",
    response_model=PipelineRead,
)
async def approve_plan(
    pipeline_id: uuid.UUID,
    body: PlanApproval,
    background_tasks: BackgroundTasks,
    svc: PipelineService = Depends(_svc),
):
    """Approve the generated plan — starts execution in background."""
    try:
        pipeline = await svc.approve_plan(pipeline_id, body.actor_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidPipelineTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Kick off the execution loop as a background task
    loop = ExecutionLoop()
    background_tasks.add_task(loop.run, pipeline_id)
    return pipeline


@router.post(
    "/pipelines/{pipeline_id}/reject-plan",
    response_model=PipelineRead,
)
async def reject_plan(
    pipeline_id: uuid.UUID,
    body: PlanRejection,
    svc: PipelineService = Depends(_svc),
):
    """Reject the generated plan with optional feedback."""
    try:
        return await svc.reject_plan(pipeline_id, body.actor_id, body.feedback)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidPipelineTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/pipelines/{pipeline_id}/pause",
    response_model=PipelineRead,
)
async def pause_pipeline(
    pipeline_id: uuid.UUID,
    svc: PipelineService = Depends(_svc),
):
    """Pause an executing pipeline."""
    try:
        return await svc.change_status(pipeline_id, "paused")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidPipelineTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/pipelines/{pipeline_id}/resume",
    response_model=PipelineRead,
)
async def resume_pipeline(
    pipeline_id: uuid.UUID,
    svc: PipelineService = Depends(_svc),
):
    """Resume a paused pipeline."""
    try:
        return await svc.change_status(pipeline_id, "executing")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidPipelineTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ─── Task Graph ───────────────────────────────────────────


class TaskGraphBody(BaseModel):
    task_graph: dict


@router.post(
    "/pipelines/{pipeline_id}/task-graph",
    response_model=PipelineRead,
)
async def set_task_graph(
    pipeline_id: uuid.UUID,
    body: TaskGraphBody,
    svc: PipelineService = Depends(_svc),
):
    """Store the task graph (from planner or manual input)."""
    try:
        return await svc.set_task_graph(pipeline_id, body.task_graph)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Contracts ────────────────────────────────────────────


@router.get(
    "/pipelines/{pipeline_id}/contracts",
    response_model=list[ContractRead],
)
async def list_contracts(
    pipeline_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all contracts for a pipeline."""
    builder = ContractBuilder(db)
    return await builder.get_contracts(pipeline_id)


@router.get(
    "/pipelines/{pipeline_id}/contracts/{contract_id}",
    response_model=ContractRead,
)
async def get_contract(
    pipeline_id: uuid.UUID,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific contract by ID."""
    builder = ContractBuilder(db)
    contract = await builder.get_contract(contract_id)
    if not contract or contract.pipeline_id != pipeline_id:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.post(
    "/pipelines/{pipeline_id}/contracts/{contract_id}/lock",
    response_model=ContractRead,
)
async def lock_contract(
    pipeline_id: uuid.UUID,
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
    "/pipelines/{pipeline_id}/generate-contracts",
    response_model=PipelineRead,
)
async def generate_contracts(
    pipeline_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger contract generation from the task graph — runs in background."""
    svc = PipelineService(db)
    pipeline = await svc.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    async def _generate():
        from openclaw.db.engine import async_session_factory

        async with async_session_factory() as gen_db:
            builder = ContractBuilder(gen_db)
            await builder.generate_contracts(pipeline_id)

    background_tasks.add_task(_generate)
    return pipeline


# ─── Budget ───────────────────────────────────────────────


@router.get(
    "/pipelines/{pipeline_id}/budget",
    response_model=BudgetLedgerRead,
)
async def get_pipeline_budget(
    pipeline_id: uuid.UUID,
    budget_svc: PipelineBudgetService = Depends(_budget_svc),
):
    """Get the budget ledger for a pipeline."""
    ledger = await budget_svc.get_ledger(pipeline_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="Budget ledger not found")
    return ledger


@router.get(
    "/pipelines/{pipeline_id}/budget/entries",
    response_model=list[BudgetEntryRead],
)
async def list_budget_entries(
    pipeline_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    budget_svc: PipelineBudgetService = Depends(_budget_svc),
):
    """List cost entries for a pipeline."""
    return await budget_svc.list_entries(pipeline_id, limit=limit)
