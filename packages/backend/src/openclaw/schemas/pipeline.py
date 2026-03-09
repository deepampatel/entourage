"""Pydantic schemas for Pipeline API requests and responses."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ─── Request schemas ──────────────────────────────────────


class PipelineCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    intent: str = Field(..., min_length=1)
    budget_limit_usd: float = Field(default=10.0, ge=0.01, le=1000.0)
    repository_id: Optional[uuid.UUID] = None
    template: Optional[str] = None  # feature, bugfix, refactor, migration


class PipelineUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    budget_limit_usd: Optional[float] = Field(None, ge=0.01, le=1000.0)


class PlanApproval(BaseModel):
    actor_id: Optional[uuid.UUID] = None


class PlanRejection(BaseModel):
    actor_id: Optional[uuid.UUID] = None
    feedback: Optional[str] = None


# ─── Response schemas ─────────────────────────────────────


class ContractLock(BaseModel):
    agent_id: uuid.UUID


# ─── Response schemas ─────────────────────────────────────


class PipelineRead(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    team_id: uuid.UUID
    repository_id: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None
    title: str
    intent: str
    status: str
    task_graph: Optional[dict] = None
    contract_set: Optional[dict] = None
    estimated_cost_usd: float
    actual_cost_usd: float
    budget_limit_usd: float
    branch_name: str
    pr_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PipelineTaskRead(BaseModel):
    id: int
    pipeline_id: uuid.UUID
    agent_id: Optional[uuid.UUID] = None
    title: str
    description: str
    complexity: str
    assigned_role: str
    status: str
    dependencies: list[int] = []
    integration_hints: list[str] = []
    estimated_tokens: int = 0
    retry_count: int = 0
    branch_name: str
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BudgetLedgerRead(BaseModel):
    id: uuid.UUID
    pipeline_id: uuid.UUID
    budget_limit_usd: float
    estimated_cost_usd: float
    actual_cost_usd: float
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetEntryRead(BaseModel):
    id: int
    pipeline_task_id: Optional[int] = None
    agent_id: Optional[uuid.UUID] = None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    recorded_at: datetime

    model_config = {"from_attributes": True}


class ContractRead(BaseModel):
    id: int
    pipeline_id: uuid.UUID
    pipeline_task_id: Optional[int] = None
    contract_type: str
    name: str
    specification: dict
    locked: bool
    locked_by: Optional[uuid.UUID] = None
    locked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
