"""Pydantic schemas for Analytics API responses."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PipelineMetrics(BaseModel):
    """Aggregate pipeline metrics for a time period."""

    total_pipelines: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    in_progress: int = 0
    avg_duration_seconds: float = 0.0
    avg_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    success_rate: float = 0.0
    pipelines_by_status: dict[str, int] = Field(default_factory=dict)
    period_start: Optional[datetime] = None


class AgentPerformance(BaseModel):
    """Per-agent performance breakdown."""

    agent_id: uuid.UUID
    agent_name: str
    role: str
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_sessions: int = 0
    avg_session_duration_seconds: float = 0.0
    total_cost_usd: float = 0.0
    avg_cost_per_task: float = 0.0
    cache_hit_rate: float = 0.0
    success_rate: float = 0.0


class CostTimeseriesPoint(BaseModel):
    """Single data point in a cost time-series."""

    period: str  # ISO date or datetime string
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    session_count: int = 0
    task_count: int = 0


class MonthlyRollup(BaseModel):
    """Monthly cost rollup."""

    month: str  # YYYY-MM
    total_cost_usd: float = 0.0
    total_sessions: int = 0
    total_tasks: int = 0


class PipelineCostDetail(BaseModel):
    """Per-task cost breakdown for a pipeline."""

    pipeline_id: uuid.UUID
    title: str
    total_cost_usd: float = 0.0
    tasks: list[dict] = Field(default_factory=list)
    # Each task dict: {task_id, title, cost_usd, tokens_in, tokens_out, agent_name}
