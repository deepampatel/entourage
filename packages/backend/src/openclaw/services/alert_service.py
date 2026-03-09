"""Alert service — evaluate budget, failure, and performance thresholds.

Learn: Checks are run periodically (via lifespan background task) against
each active team. Alerts are persisted to the alerts table and deduplicated
(same kind within 1 hour is not re-fired). Acknowledging an alert marks it
resolved without affecting future evaluations.

Budget thresholds come from Organization.config JSONB:
  {"monthly_budget_cap_usd": 500.0, "budget_warning_threshold": 0.8}
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import (
    Alert,
    BudgetEntry,
    Organization,
    Pipeline,
    Session,
    Team,
)
from openclaw.events.store import EventStore
from openclaw.events.types import (
    ALERT_BUDGET_EXCEEDED,
    ALERT_BUDGET_WARNING,
    ALERT_FAILURE_SPIKE,
    ALERT_PERFORMANCE,
)

logger = logging.getLogger("openclaw.services.alert_service")


@dataclass
class AlertData:
    """Alert payload before persistence."""

    kind: str  # budget_warning|budget_exceeded|failure_spike|performance
    team_id: str
    org_id: str
    severity: str  # warning|critical
    message: str
    data: dict = field(default_factory=dict)


class AlertService:
    """Evaluate alert conditions and persist new alerts."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def evaluate_all(self, team_id: str) -> list[AlertData]:
        """Run all alert checks for a team. Returns newly fired alerts."""
        team = await self._db.get(Team, team_id)
        if not team:
            return []

        org = await self._db.get(Organization, team.org_id)
        if not org:
            return []

        alerts: list[AlertData] = []
        alerts.extend(await self._check_budget(team, org))
        alerts.extend(await self._check_failure_rate(team, org))
        alerts.extend(await self._check_performance(team, org))

        # Persist and deduplicate
        persisted = []
        for alert_data in alerts:
            if not await self._is_duplicate(alert_data):
                alert = Alert(
                    kind=alert_data.kind,
                    team_id=team.id,
                    org_id=org.id,
                    severity=alert_data.severity,
                    message=alert_data.message,
                    alert_data=alert_data.data,
                )
                self._db.add(alert)
                persisted.append(alert_data)

        if persisted:
            await self._db.commit()

        return persisted

    async def _check_budget(
        self, team: Team, org: Organization
    ) -> list[AlertData]:
        """Check monthly spend against org budget cap."""
        config = getattr(org, "config", None) or {}
        monthly_cap = config.get("monthly_budget_cap_usd")
        if not monthly_cap:
            return []

        warning_threshold = config.get("budget_warning_threshold", 0.8)

        # Calculate current month's spend for this team
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        q = select(func.coalesce(func.sum(BudgetEntry.cost_usd), 0)).where(
            BudgetEntry.recorded_at >= month_start,
        )
        result = await self._db.execute(q)
        current_spend = float(result.scalar() or 0)

        alerts = []
        ratio = current_spend / monthly_cap

        if ratio >= 1.0:
            alerts.append(
                AlertData(
                    kind="budget_exceeded",
                    team_id=str(team.id),
                    org_id=str(org.id),
                    severity="critical",
                    message=f"Monthly budget exceeded: ${current_spend:.2f} / ${monthly_cap:.2f}",
                    data={
                        "current_spend": current_spend,
                        "monthly_cap": monthly_cap,
                        "ratio": round(ratio, 3),
                    },
                )
            )
        elif ratio >= warning_threshold:
            alerts.append(
                AlertData(
                    kind="budget_warning",
                    team_id=str(team.id),
                    org_id=str(org.id),
                    severity="warning",
                    message=f"Approaching budget limit: ${current_spend:.2f} / ${monthly_cap:.2f} ({ratio:.0%})",
                    data={
                        "current_spend": current_spend,
                        "monthly_cap": monthly_cap,
                        "ratio": round(ratio, 3),
                    },
                )
            )

        return alerts

    async def _check_failure_rate(
        self, team: Team, org: Organization
    ) -> list[AlertData]:
        """Alert if 3+ consecutive pipeline failures."""
        q = (
            select(Pipeline.status)
            .where(Pipeline.team_id == team.id)
            .order_by(Pipeline.updated_at.desc())
            .limit(5)
        )
        result = await self._db.execute(q)
        statuses = [row[0] for row in result.all()]

        if not statuses:
            return []

        # Count consecutive failures from most recent
        consecutive_failures = 0
        for status in statuses:
            if status == "failed":
                consecutive_failures += 1
            else:
                break

        if consecutive_failures >= 3:
            return [
                AlertData(
                    kind="failure_spike",
                    team_id=str(team.id),
                    org_id=str(org.id),
                    severity="warning",
                    message=f"{consecutive_failures} consecutive pipeline failures detected",
                    data={"consecutive_failures": consecutive_failures},
                )
            ]

        return []

    async def _check_performance(
        self, team: Team, org: Organization
    ) -> list[AlertData]:
        """Alert if avg session duration > 2x 30-day historical average."""
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # Compute duration as EXTRACT(EPOCH FROM ended_at - started_at)
        duration_expr = extract(
            "epoch", Session.ended_at - Session.started_at
        )

        # 30-day baseline average
        q_baseline = select(func.avg(duration_expr)).where(
            Session.started_at >= thirty_days_ago,
            Session.ended_at.isnot(None),
        )
        result = await self._db.execute(q_baseline)
        baseline_avg = float(result.scalar() or 0)

        if baseline_avg <= 0:
            return []

        # Recent 7-day average
        q_recent = select(func.avg(duration_expr)).where(
            Session.started_at >= seven_days_ago,
            Session.ended_at.isnot(None),
        )
        result = await self._db.execute(q_recent)
        recent_avg = float(result.scalar() or 0)

        if recent_avg > 2 * baseline_avg:
            return [
                AlertData(
                    kind="performance",
                    team_id=str(team.id),
                    org_id=str(org.id),
                    severity="warning",
                    message=(
                        f"Session duration spike: {recent_avg:.0f}s avg "
                        f"(vs {baseline_avg:.0f}s baseline)"
                    ),
                    data={
                        "recent_avg_seconds": round(recent_avg, 1),
                        "baseline_avg_seconds": round(baseline_avg, 1),
                        "ratio": round(recent_avg / baseline_avg, 2),
                    },
                )
            ]

        return []

    async def _is_duplicate(self, alert_data: AlertData) -> bool:
        """Check if same alert kind was fired within the last hour."""
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        q = (
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.kind == alert_data.kind,
                Alert.team_id == alert_data.team_id,
                Alert.created_at >= one_hour_ago,
            )
        )
        result = await self._db.execute(q)
        return (result.scalar() or 0) > 0

    async def list_alerts(
        self,
        team_id: str,
        acknowledged: Optional[bool] = None,
        limit: int = 50,
    ) -> list[Alert]:
        """Query alerts for a team."""
        q = (
            select(Alert)
            .where(Alert.team_id == team_id)
            .order_by(Alert.created_at.desc())
            .limit(limit)
        )
        if acknowledged is not None:
            q = q.where(Alert.acknowledged == acknowledged)

        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def acknowledge(self, alert_id: int, user_id: str) -> Optional[Alert]:
        """Mark an alert as acknowledged."""
        alert = await self._db.get(Alert, alert_id)
        if not alert:
            return None

        alert.acknowledged = True
        alert.acknowledged_by = user_id
        alert.acknowledged_at = datetime.now(timezone.utc)
        await self._db.commit()
        return alert
