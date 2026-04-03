"""Run service — business logic for run CRUD and state machine.

The run state machine enforces the orchestration workflow:
  draft → planning → awaiting_plan_approval → executing →
  reviewing → merging → done

With escape states: paused, failed, cancelled.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from openclaw.db.models import BudgetLedger, Run, RunTask, Team
from openclaw.events.store import EventStore
from openclaw.events.types import (
    RUN_CREATED,
    RUN_PLAN_APPROVED,
    RUN_PLAN_REJECTED,
    RUN_STATUS_CHANGED,
)


# ═══════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════

VALID_RUN_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"planning", "cancelled"},
    "planning": {"contracting", "awaiting_plan_approval", "failed", "cancelled"},
    "contracting": {"awaiting_plan_approval", "failed", "cancelled"},
    "awaiting_plan_approval": {"executing", "planning", "cancelled"},
    "executing": {"reviewing", "paused", "failed", "cancelled"},
    "reviewing": {"merging", "done", "executing", "failed", "cancelled"},
    "merging": {"done", "failed"},
    "paused": {"executing", "cancelled"},
    "done": set(),
    "failed": {"draft"},
    "cancelled": set(),
}


class InvalidRunTransitionError(Exception):
    """Raised when a run status transition is not allowed."""
    pass


# ═══════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════


class RunService:
    """Business logic for run CRUD and state management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)

    # ─── Create ──────────────────────────────────────────

    async def create_run(
        self,
        team_id: uuid.UUID,
        title: str,
        intent: str,
        created_by: Optional[uuid.UUID] = None,
        budget_limit: float = 10.0,
        repository_id: Optional[uuid.UUID] = None,
    ) -> Run:
        """Create a new run in draft status."""
        # Look up org_id from team
        team = await self.db.get(Team, team_id)
        if not team:
            raise ValueError(f"Team {team_id} not found")

        run = Run(
            org_id=team.org_id,
            team_id=team_id,
            title=title,
            intent=intent,
            created_by=created_by,
            budget_limit_usd=budget_limit,
            repository_id=repository_id,
            status="draft",
        )
        self.db.add(run)
        await self.db.flush()

        # Create budget ledger
        ledger = BudgetLedger(
            run_id=run.id,
            org_id=team.org_id,
            team_id=team_id,
            budget_limit_usd=budget_limit,
        )
        self.db.add(ledger)

        await self.events.append(
            stream_id=f"run:{run.id}",
            event_type=RUN_CREATED,
            data={
                "run_id": str(run.id),
                "team_id": str(team_id),
                "title": title,
                "intent": intent,
                "budget_limit_usd": budget_limit,
            },
        )
        await self.db.commit()
        return run

    # ─── Read ────────────────────────────────────────────

    async def get_run(self, run_id: uuid.UUID) -> Optional[Run]:
        """Get a run by ID with tasks eagerly loaded."""
        result = await self.db.execute(
            select(Run)
            .where(Run.id == run_id)
            .options(selectinload(Run.run_tasks))
        )
        return result.scalars().first()

    async def list_runs(
        self,
        team_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        """List runs for a team, optionally filtered by status."""
        q = (
            select(Run)
            .where(Run.team_id == team_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            q = q.where(Run.status == status)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_run_tasks(
        self, run_id: uuid.UUID
    ) -> list[RunTask]:
        """List all tasks for a run."""
        result = await self.db.execute(
            select(RunTask)
            .where(RunTask.run_id == run_id)
            .order_by(RunTask.id)
        )
        return list(result.scalars().all())

    # ─── State transitions ───────────────────────────────

    async def change_status(
        self,
        run_id: uuid.UUID,
        new_status: str,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Run:
        """Transition run to a new status (validated)."""
        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        old_status = run.status
        valid = VALID_RUN_TRANSITIONS.get(old_status, set())
        if new_status not in valid:
            raise InvalidRunTransitionError(
                f"Cannot transition from '{old_status}' to '{new_status}'. "
                f"Valid: {valid}"
            )

        run.status = new_status
        if new_status == "done":
            run.completed_at = datetime.now(timezone.utc)

        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_STATUS_CHANGED,
            data={
                "run_id": str(run_id),
                "from": old_status,
                "to": new_status,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        await self.db.commit()
        return run

    async def approve_plan(
        self,
        run_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Run:
        """Approve the plan — transitions to executing and assigns branch names.

        Branch naming:
        - Run: feature/run-{short_id}
        - Each RunTask: task/{id}-{slug}
        """
        import re

        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run.status != "awaiting_plan_approval":
            raise InvalidRunTransitionError(
                f"Cannot approve plan: run is '{run.status}', "
                f"expected 'awaiting_plan_approval'"
            )

        # Assign feature branch name for the run
        short_id = str(run_id)[:8]
        run.branch_name = f"feature/run-{short_id}"

        # Assign branch names to all RunTasks
        result = await self.db.execute(
            select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.id)
        )
        for rt in result.scalars().all():
            slug = re.sub(r"[^a-z0-9]+", "-", rt.title.lower())[:40].strip("-")
            rt.branch_name = f"task/{rt.id}-{slug}"

        run.status = "executing"
        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_PLAN_APPROVED,
            data={
                "run_id": str(run_id),
                "actor_id": str(actor_id) if actor_id else None,
                "branch": run.branch_name,
            },
        )
        await self.db.commit()
        return run

    async def reject_plan(
        self,
        run_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
        feedback: Optional[str] = None,
    ) -> Run:
        """Reject the plan — transitions back to draft with feedback."""
        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        if run.status != "awaiting_plan_approval":
            raise InvalidRunTransitionError(
                f"Cannot reject plan: run is '{run.status}', "
                f"expected 'awaiting_plan_approval'"
            )

        run.status = "draft"
        if feedback:
            meta = run.run_metadata or {}
            rejections = meta.get("plan_rejections", [])
            rejections.append({
                "feedback": feedback,
                "actor_id": str(actor_id) if actor_id else None,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            run.run_metadata = {**meta, "plan_rejections": rejections}
            flag_modified(run, "run_metadata")

        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_PLAN_REJECTED,
            data={
                "run_id": str(run_id),
                "feedback": feedback,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        await self.db.commit()
        return run

    # ─── Task graph ──────────────────────────────────────

    async def set_task_graph(
        self, run_id: uuid.UUID, task_graph: dict
    ) -> Run:
        """Store the task graph and create RunTask rows from it."""
        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        run.task_graph = task_graph
        flag_modified(run, "task_graph")

        # Validate task graph dependencies
        tasks_data = task_graph.get("tasks", [])
        self._validate_dependencies(tasks_data)

        # Create RunTask rows from the task_graph
        for i, t in enumerate(tasks_data):
            ptask = RunTask(
                run_id=run_id,
                title=t["title"],
                description=t.get("description", ""),
                complexity=t.get("complexity", "M"),
                assigned_role=t.get("assigned_role", "engineer"),
                dependencies=t.get("dependencies", []),
                integration_hints=t.get("integration_hints", []),
                estimated_tokens=t.get("estimated_tokens", 0),
            )
            self.db.add(ptask)

        await self.db.commit()
        return run

    @staticmethod
    def _validate_dependencies(tasks: list[dict]) -> None:
        """Validate task graph: no invalid indices, no cycles."""
        n = len(tasks)

        for i, t in enumerate(tasks):
            for dep in t.get("dependencies", []):
                if not isinstance(dep, int) or dep < 0 or dep >= n:
                    raise ValueError(
                        f"Task {i} ('{t.get('title', '')}') has invalid dependency "
                        f"index {dep}. Must be 0-{n-1}."
                    )
                if dep == i:
                    raise ValueError(
                        f"Task {i} depends on itself."
                    )

        # Cycle detection via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color = [WHITE] * n

        def dfs(node: int) -> None:
            color[node] = GRAY
            for dep in tasks[node].get("dependencies", []):
                if color[dep] == GRAY:
                    raise ValueError(
                        f"Circular dependency: task {node} → task {dep}"
                    )
                if color[dep] == WHITE:
                    dfs(dep)
            color[node] = BLACK

        for i in range(n):
            if color[i] == WHITE:
                dfs(i)

    # ─── Cost tracking ───────────────────────────────────

    async def update_cost(
        self, run_id: uuid.UUID, cost_delta: float
    ) -> Run:
        """Add cost to the run's running total."""
        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        run.actual_cost_usd = float(run.actual_cost_usd) + cost_delta
        await self.db.commit()
        return run
