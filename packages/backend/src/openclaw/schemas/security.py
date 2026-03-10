"""Security schemas for API serialization."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SecurityViolationRead(BaseModel):
    """Security violation response schema."""

    id: int
    kind: str
    agent_id: str
    team_id: str
    run_task_id: Optional[int] = None
    detail: str
    rule: str
    action: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SecuritySummary(BaseModel):
    """Aggregated violation summary."""

    total_violations: int
    by_kind: dict[str, int]
    by_agent: dict[str, int]
    period_days: int


class NetworkAllowlistUpdate(BaseModel):
    """Request to add a domain to the network allowlist."""

    domain: str
