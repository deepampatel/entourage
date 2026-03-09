"""Alerts API — list, acknowledge, and manage budget alerts.

Learn: Alert evaluation happens in a background loop (lifespan),
not on request. These endpoints only query/update existing alerts.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.auth.dependencies import CurrentIdentity, get_current_user
from openclaw.db.engine import get_db
from openclaw.db.models import Alert, BudgetEntry, Organization, Team
from openclaw.schemas.alerts import AlertRead, BudgetCapUpdate, OrgBudgetStatus
from openclaw.services.alert_service import AlertService

router = APIRouter()


@router.get("/teams/{team_id}/alerts", response_model=list[AlertRead])
async def list_alerts(
    team_id: uuid.UUID,
    acknowledged: bool | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List alerts for a team, optionally filtered by acknowledged status."""
    svc = AlertService(db)
    alerts = await svc.list_alerts(
        team_id=str(team_id),
        acknowledged=acknowledged,
        limit=limit,
    )
    return alerts


@router.post("/teams/{team_id}/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(
    team_id: uuid.UUID,
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    identity: CurrentIdentity = Depends(get_current_user),
):
    """Acknowledge (dismiss) an alert."""
    svc = AlertService(db)
    alert = await svc.acknowledge(alert_id, identity.user_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/orgs/{org_id}/budget", response_model=OrgBudgetStatus)
async def get_org_budget(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get current budget status for an organization."""
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    config = getattr(org, "config", None) or {}
    monthly_cap = config.get("monthly_budget_cap_usd")
    warning_threshold = config.get("budget_warning_threshold", 0.8)

    # Calculate current month's spend
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    q = select(func.coalesce(func.sum(BudgetEntry.cost_usd), 0)).where(
        BudgetEntry.recorded_at >= month_start,
    )
    result = await db.execute(q)
    current_spend = float(result.scalar() or 0)

    # Determine status
    if monthly_cap and current_spend >= monthly_cap:
        status = "exceeded"
    elif monthly_cap and current_spend >= monthly_cap * warning_threshold:
        status = "warning"
    else:
        status = "ok"

    return OrgBudgetStatus(
        org_id=str(org_id),
        monthly_cap_usd=monthly_cap,
        warning_threshold=warning_threshold,
        current_month_spend=current_spend,
        status=status,
    )


@router.post("/orgs/{org_id}/budget", response_model=OrgBudgetStatus)
async def set_org_budget(
    org_id: uuid.UUID,
    body: BudgetCapUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Set or update org-level budget cap."""
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not hasattr(org, "config") or org.config is None:
        org.config = {}

    org.config = {
        **org.config,
        "monthly_budget_cap_usd": body.monthly_budget_cap_usd,
        "budget_warning_threshold": body.budget_warning_threshold,
    }
    await db.commit()

    # Return updated status
    return await get_org_budget(org_id, db)
