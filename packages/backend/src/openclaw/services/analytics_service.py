"""Analytics service — read-only aggregation queries over runs, sessions, and costs.

Provides run metrics, agent performance rankings, cost time-series,
and monthly rollups. All queries are read-only — no state mutations.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, cast, extract, func, select, Float, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import (
    Agent,
    BudgetEntry,
    BudgetLedger,
    Run,
    RunTask,
    Session,
)


def _period_start(period: str) -> datetime:
    """Convert a period name to a start datetime."""
    now = datetime.now(timezone.utc)
    if period == "day":
        return now - timedelta(days=1)
    elif period == "week":
        return now - timedelta(weeks=1)
    elif period == "month":
        return now - timedelta(days=30)
    else:  # "all"
        return datetime(2020, 1, 1, tzinfo=timezone.utc)


class AnalyticsService:
    """Read-only analytics queries over existing tables."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_run_metrics(
        self, team_id: uuid.UUID, period: str = "week"
    ) -> dict:
        """Aggregate run metrics for a team within a time period.

        Returns total/completed/failed/cancelled counts, average duration,
        average cost, total cost, success rate, and run-by-status breakdown.
        """
        start = _period_start(period)

        # Base query: runs for this team within the period
        base = select(Run).where(
            Run.team_id == team_id,
            Run.created_at >= start,
        )
        result = await self.db.execute(base)
        runs = list(result.scalars().all())

        if not runs:
            return {
                "total_runs": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "in_progress": 0,
                "avg_duration_seconds": 0.0,
                "avg_cost_usd": 0.0,
                "total_cost_usd": 0.0,
                "success_rate": 0.0,
                "runs_by_status": {},
                "period_start": start.isoformat(),
            }

        # Count by status
        status_counts: dict[str, int] = {}
        completed = 0
        failed = 0
        cancelled = 0
        in_progress = 0
        durations: list[float] = []
        costs: list[float] = []

        for p in runs:
            status_counts[p.status] = status_counts.get(p.status, 0) + 1

            if p.status == "done":
                completed += 1
                if p.completed_at and p.created_at:
                    dur = (p.completed_at - p.created_at).total_seconds()
                    durations.append(dur)
            elif p.status == "failed":
                failed += 1
            elif p.status == "cancelled":
                cancelled += 1
            elif p.status in ("executing", "reviewing", "merging", "planning"):
                in_progress += 1

            costs.append(float(p.actual_cost_usd or 0))

        total = len(runs)
        terminal = completed + failed + cancelled
        success_rate = (completed / terminal * 100) if terminal > 0 else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        total_cost = sum(costs)
        avg_cost = total_cost / total if total > 0 else 0.0

        return {
            "total_runs": total,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "in_progress": in_progress,
            "avg_duration_seconds": round(avg_duration, 1),
            "avg_cost_usd": round(avg_cost, 6),
            "total_cost_usd": round(total_cost, 6),
            "success_rate": round(success_rate, 1),
            "runs_by_status": status_counts,
            "period_start": start.isoformat(),
        }

    async def get_agent_performance(
        self, team_id: uuid.UUID, period: str = "week"
    ) -> list[dict]:
        """Per-agent performance breakdown.

        Returns tasks completed/failed, sessions, average duration,
        total cost, average cost per task, cache hit rate, success rate.
        """
        start = _period_start(period)

        # Get all agents for this team
        result = await self.db.execute(
            select(Agent).where(Agent.team_id == team_id)
        )
        agents = list(result.scalars().all())

        performances = []

        for agent in agents:
            # Get sessions for this agent within the period
            sess_result = await self.db.execute(
                select(Session).where(
                    Session.agent_id == agent.id,
                    Session.started_at >= start,
                )
            )
            sessions = list(sess_result.scalars().all())

            # Get run tasks assigned to this agent within the period
            task_result = await self.db.execute(
                select(RunTask).where(
                    RunTask.agent_id == agent.id,
                    RunTask.created_at >= start,
                )
            )
            tasks = list(task_result.scalars().all())

            tasks_completed = sum(1 for t in tasks if t.status == "done")
            tasks_failed = sum(1 for t in tasks if t.status == "failed")

            total_cost = sum(float(s.cost_usd or 0) for s in sessions)
            total_tokens_in = sum(s.tokens_in or 0 for s in sessions)
            total_cache_read = sum(s.cache_read or 0 for s in sessions)

            # Calculate durations for completed sessions
            durations = []
            for s in sessions:
                if s.started_at and s.ended_at:
                    dur = (s.ended_at - s.started_at).total_seconds()
                    durations.append(dur)

            avg_duration = sum(durations) / len(durations) if durations else 0.0
            total_tasks = tasks_completed + tasks_failed
            avg_cost_per_task = total_cost / total_tasks if total_tasks > 0 else 0.0

            # Cache hit rate: cache_read / (tokens_in + cache_read)
            total_input_tokens = total_tokens_in + total_cache_read
            cache_hit_rate = (
                (total_cache_read / total_input_tokens * 100)
                if total_input_tokens > 0
                else 0.0
            )

            success_rate = (
                (tasks_completed / total_tasks * 100) if total_tasks > 0 else 0.0
            )

            performances.append({
                "agent_id": agent.id,
                "agent_name": agent.name,
                "role": agent.role,
                "tasks_completed": tasks_completed,
                "tasks_failed": tasks_failed,
                "total_sessions": len(sessions),
                "avg_session_duration_seconds": round(avg_duration, 1),
                "total_cost_usd": round(total_cost, 6),
                "avg_cost_per_task": round(avg_cost_per_task, 6),
                "cache_hit_rate": round(cache_hit_rate, 1),
                "success_rate": round(success_rate, 1),
            })

        # Sort by total_cost descending (most expensive agents first)
        performances.sort(key=lambda p: p["total_cost_usd"], reverse=True)
        return performances

    async def get_cost_timeseries(
        self,
        team_id: uuid.UUID,
        granularity: str = "day",
        days: int = 30,
    ) -> list[dict]:
        """Time-series cost data at the specified granularity.

        Returns list of data points with period, cost, tokens, session count.
        """
        start = datetime.now(timezone.utc) - timedelta(days=days)

        # Get sessions for this team within the period
        # Sessions are linked to agents which are linked to teams
        result = await self.db.execute(
            select(Session)
            .join(Agent, Session.agent_id == Agent.id)
            .where(
                Agent.team_id == team_id,
                Session.started_at >= start,
            )
            .order_by(Session.started_at)
        )
        sessions = list(result.scalars().all())

        # Bucket sessions by granularity
        buckets: dict[str, dict] = {}
        for session in sessions:
            if not session.started_at:
                continue

            if granularity == "hour":
                key = session.started_at.strftime("%Y-%m-%dT%H:00")
            elif granularity == "day":
                key = session.started_at.strftime("%Y-%m-%d")
            else:  # week
                # ISO week
                iso_year, iso_week, _ = session.started_at.isocalendar()
                key = f"{iso_year}-W{iso_week:02d}"

            if key not in buckets:
                buckets[key] = {
                    "period": key,
                    "cost_usd": 0.0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "session_count": 0,
                    "task_count": 0,
                }

            bucket = buckets[key]
            bucket["cost_usd"] += float(session.cost_usd or 0)
            bucket["tokens_in"] += session.tokens_in or 0
            bucket["tokens_out"] += session.tokens_out or 0
            bucket["session_count"] += 1
            if session.task_id:
                bucket["task_count"] += 1

        # Sort by period
        points = sorted(buckets.values(), key=lambda p: p["period"])

        # Round costs
        for p in points:
            p["cost_usd"] = round(p["cost_usd"], 6)

        return points

    async def get_run_cost_detail(
        self, run_id: uuid.UUID
    ) -> dict:
        """Per-task cost breakdown for a run.

        Returns run info plus per-task cost entries from BudgetEntry.
        """
        # Get run
        result = await self.db.execute(
            select(Run).where(Run.id == run_id)
        )
        run = result.scalars().first()
        if not run:
            return {
                "run_id": run_id,
                "title": "",
                "total_cost_usd": 0.0,
                "tasks": [],
            }

        # Get budget entries grouped by task
        entry_result = await self.db.execute(
            select(BudgetEntry)
            .where(BudgetEntry.run_id == run_id)
            .order_by(BudgetEntry.recorded_at)
        )
        entries = list(entry_result.scalars().all())

        # Get run tasks for names
        task_result = await self.db.execute(
            select(RunTask).where(RunTask.run_id == run_id)
        )
        tasks = {t.id: t for t in task_result.scalars().all()}

        # Get agents for names
        agent_ids = {e.agent_id for e in entries if e.agent_id}
        agents: dict[uuid.UUID, str] = {}
        if agent_ids:
            agent_result = await self.db.execute(
                select(Agent).where(Agent.id.in_(agent_ids))
            )
            agents = {a.id: a.name for a in agent_result.scalars().all()}

        # Group entries by task
        task_costs: dict[Optional[int], dict] = {}
        for entry in entries:
            tid = entry.run_task_id
            if tid not in task_costs:
                task_obj = tasks.get(tid) if tid else None
                task_costs[tid] = {
                    "task_id": tid,
                    "title": task_obj.title if task_obj else "Run overhead",
                    "cost_usd": 0.0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "agent_name": agents.get(entry.agent_id, "unknown")
                    if entry.agent_id
                    else None,
                }
            tc = task_costs[tid]
            tc["cost_usd"] += float(entry.cost_usd or 0)
            tc["tokens_in"] += entry.input_tokens or 0
            tc["tokens_out"] += entry.output_tokens or 0

        # Round costs
        for tc in task_costs.values():
            tc["cost_usd"] = round(tc["cost_usd"], 6)

        return {
            "run_id": run_id,
            "title": run.title,
            "total_cost_usd": round(float(run.actual_cost_usd or 0), 6),
            "tasks": list(task_costs.values()),
        }

    async def get_monthly_rollup(
        self, team_id: uuid.UUID, months: int = 6
    ) -> list[dict]:
        """Monthly cost rollup for a team.

        Returns list of monthly data points with cost, sessions, tasks.
        """
        start = datetime.now(timezone.utc) - timedelta(days=months * 31)

        # Get sessions grouped by month
        result = await self.db.execute(
            select(Session)
            .join(Agent, Session.agent_id == Agent.id)
            .where(
                Agent.team_id == team_id,
                Session.started_at >= start,
            )
            .order_by(Session.started_at)
        )
        sessions = list(result.scalars().all())

        # Bucket by month
        buckets: dict[str, dict] = {}
        for session in sessions:
            if not session.started_at:
                continue
            month_key = session.started_at.strftime("%Y-%m")
            if month_key not in buckets:
                buckets[month_key] = {
                    "month": month_key,
                    "total_cost_usd": 0.0,
                    "total_sessions": 0,
                    "total_tasks": 0,
                }
            bucket = buckets[month_key]
            bucket["total_cost_usd"] += float(session.cost_usd or 0)
            bucket["total_sessions"] += 1
            if session.task_id:
                bucket["total_tasks"] += 1

        # Sort by month
        points = sorted(buckets.values(), key=lambda p: p["month"])

        # Round costs
        for p in points:
            p["total_cost_usd"] = round(p["total_cost_usd"], 6)

        return points
