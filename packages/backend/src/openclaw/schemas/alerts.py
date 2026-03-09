"""Alert schemas for API serialization.

Learn: Pydantic v2 models with from_attributes=True for ORM compat.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AlertRead(BaseModel):
    """Alert response schema."""

    id: int
    kind: str
    severity: str
    message: str
    alert_data: dict
    acknowledged: bool
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgBudgetStatus(BaseModel):
    """Current budget status for an organization."""

    org_id: str
    monthly_cap_usd: Optional[float] = None
    warning_threshold: float = 0.8
    current_month_spend: float
    status: str  # ok|warning|exceeded

    model_config = {"from_attributes": True}


class BudgetCapUpdate(BaseModel):
    """Request to set/update org budget cap."""

    monthly_budget_cap_usd: Optional[float] = None
    budget_warning_threshold: float = 0.8
