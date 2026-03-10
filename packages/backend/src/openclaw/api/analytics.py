"""Analytics API routes — run metrics, agent performance, and cost breakdowns.

Read-only aggregation endpoints for dashboards and reporting.
All queries operate over existing sessions, runs, and budget entries.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import get_db
from openclaw.schemas.analytics import (
    AgentPerformance,
    CostTimeseriesPoint,
    MonthlyRollup,
    RunCostDetail,
    RunMetrics,
)
from openclaw.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics")


def _svc(db: AsyncSession = Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(db)


# ─── Run metrics ────────────────────────────────────────


@router.get("/{team_id}/runs", response_model=RunMetrics)
async def get_run_metrics(
    team_id: uuid.UUID,
    period: str = Query("week", pattern="^(day|week|month|all)$"),
    svc: AnalyticsService = Depends(_svc),
):
    """Aggregate run metrics for a team within a time period."""
    return await svc.get_run_metrics(team_id=team_id, period=period)


# ─── Agent performance ───────────────────────────────────────


@router.get("/{team_id}/agents", response_model=list[AgentPerformance])
async def get_agent_performance(
    team_id: uuid.UUID,
    period: str = Query("week", pattern="^(day|week|month|all)$"),
    svc: AnalyticsService = Depends(_svc),
):
    """Per-agent performance breakdown for a team."""
    return await svc.get_agent_performance(team_id=team_id, period=period)


# ─── Cost time-series ────────────────────────────────────────


@router.get("/{team_id}/costs", response_model=list[CostTimeseriesPoint])
async def get_cost_timeseries(
    team_id: uuid.UUID,
    granularity: str = Query("day", pattern="^(hour|day|week)$"),
    days: int = Query(30, ge=1, le=365),
    svc: AnalyticsService = Depends(_svc),
):
    """Time-series cost data at the specified granularity."""
    return await svc.get_cost_timeseries(
        team_id=team_id, granularity=granularity, days=days
    )


# ─── Monthly rollup ──────────────────────────────────────────


@router.get("/{team_id}/costs/monthly", response_model=list[MonthlyRollup])
async def get_monthly_rollup(
    team_id: uuid.UUID,
    months: int = Query(6, ge=1, le=24),
    svc: AnalyticsService = Depends(_svc),
):
    """Monthly cost rollup for a team."""
    return await svc.get_monthly_rollup(team_id=team_id, months=months)


# ─── Run cost detail ────────────────────────────────────


@router.get("/runs/{run_id}/costs", response_model=RunCostDetail)
async def get_run_cost_detail(
    run_id: uuid.UUID,
    svc: AnalyticsService = Depends(_svc),
):
    """Per-task cost breakdown for a specific run."""
    result = await svc.get_run_cost_detail(run_id=run_id)
    if not result.get("title"):
        raise HTTPException(status_code=404, detail="Run not found")
    return result
