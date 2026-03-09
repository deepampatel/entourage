"""Pipeline service — business logic for pipeline CRUD and state machine.

The pipeline state machine enforces the orchestration workflow:
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

from openclaw.db.models import BudgetLedger, Pipeline, PipelineTask, Team
from openclaw.events.store import EventStore
from openclaw.events.types import (
    PIPELINE_CREATED,
    PIPELINE_PLAN_APPROVED,
    PIPELINE_PLAN_REJECTED,
    PIPELINE_STATUS_CHANGED,
)


# ═══════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════

VALID_PIPELINE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"planning", "cancelled"},
    "planning": {"awaiting_plan_approval", "failed", "cancelled"},
    "awaiting_plan_approval": {"executing", "planning", "cancelled"},
    "executing": {"reviewing", "paused", "failed", "cancelled"},
    "reviewing": {"merging", "executing", "failed", "cancelled"},
    "merging": {"done", "failed"},
    "paused": {"executing", "cancelled"},
    "done": set(),
    "failed": {"draft"},
    "cancelled": set(),
}


class InvalidPipelineTransitionError(Exception):
    """Raised when a pipeline status transition is not allowed."""
    pass


# ═══════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════


class PipelineService:
    """Business logic for pipeline CRUD and state management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)

    # ─── Create ──────────────────────────────────────────

    async def create_pipeline(
        self,
        team_id: uuid.UUID,
        title: str,
        intent: str,
        created_by: Optional[uuid.UUID] = None,
        budget_limit: float = 10.0,
        repository_id: Optional[uuid.UUID] = None,
    ) -> Pipeline:
        """Create a new pipeline in draft status."""
        # Look up org_id from team
        team = await self.db.get(Team, team_id)
        if not team:
            raise ValueError(f"Team {team_id} not found")

        pipeline = Pipeline(
            org_id=team.org_id,
            team_id=team_id,
            title=title,
            intent=intent,
            created_by=created_by,
            budget_limit_usd=budget_limit,
            repository_id=repository_id,
            status="draft",
        )
        self.db.add(pipeline)
        await self.db.flush()

        # Create budget ledger
        ledger = BudgetLedger(
            pipeline_id=pipeline.id,
            org_id=team.org_id,
            team_id=team_id,
            budget_limit_usd=budget_limit,
        )
        self.db.add(ledger)

        await self.events.append(
            stream_id=f"pipeline:{pipeline.id}",
            event_type=PIPELINE_CREATED,
            data={
                "pipeline_id": str(pipeline.id),
                "team_id": str(team_id),
                "title": title,
                "intent": intent,
                "budget_limit_usd": budget_limit,
            },
        )
        await self.db.commit()
        return pipeline

    # ─── Read ────────────────────────────────────────────

    async def get_pipeline(self, pipeline_id: uuid.UUID) -> Optional[Pipeline]:
        """Get a pipeline by ID with tasks eagerly loaded."""
        result = await self.db.execute(
            select(Pipeline)
            .where(Pipeline.id == pipeline_id)
            .options(selectinload(Pipeline.pipeline_tasks))
        )
        return result.scalars().first()

    async def list_pipelines(
        self,
        team_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Pipeline]:
        """List pipelines for a team, optionally filtered by status."""
        q = (
            select(Pipeline)
            .where(Pipeline.team_id == team_id)
            .order_by(Pipeline.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            q = q.where(Pipeline.status == status)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_pipeline_tasks(
        self, pipeline_id: uuid.UUID
    ) -> list[PipelineTask]:
        """List all tasks for a pipeline."""
        result = await self.db.execute(
            select(PipelineTask)
            .where(PipelineTask.pipeline_id == pipeline_id)
            .order_by(PipelineTask.id)
        )
        return list(result.scalars().all())

    # ─── State transitions ───────────────────────────────

    async def change_status(
        self,
        pipeline_id: uuid.UUID,
        new_status: str,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Pipeline:
        """Transition pipeline to a new status (validated)."""
        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        old_status = pipeline.status
        valid = VALID_PIPELINE_TRANSITIONS.get(old_status, set())
        if new_status not in valid:
            raise InvalidPipelineTransitionError(
                f"Cannot transition from '{old_status}' to '{new_status}'. "
                f"Valid: {valid}"
            )

        pipeline.status = new_status
        if new_status == "done":
            pipeline.completed_at = datetime.now(timezone.utc)

        await self.events.append(
            stream_id=f"pipeline:{pipeline_id}",
            event_type=PIPELINE_STATUS_CHANGED,
            data={
                "pipeline_id": str(pipeline_id),
                "from": old_status,
                "to": new_status,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        await self.db.commit()
        return pipeline

    async def approve_plan(
        self,
        pipeline_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Pipeline:
        """Approve the plan — transitions from awaiting_plan_approval to executing."""
        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        if pipeline.status != "awaiting_plan_approval":
            raise InvalidPipelineTransitionError(
                f"Cannot approve plan: pipeline is '{pipeline.status}', "
                f"expected 'awaiting_plan_approval'"
            )

        pipeline.status = "executing"
        await self.events.append(
            stream_id=f"pipeline:{pipeline_id}",
            event_type=PIPELINE_PLAN_APPROVED,
            data={
                "pipeline_id": str(pipeline_id),
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        await self.db.commit()
        return pipeline

    async def reject_plan(
        self,
        pipeline_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
        feedback: Optional[str] = None,
    ) -> Pipeline:
        """Reject the plan — transitions back to draft with feedback."""
        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        if pipeline.status != "awaiting_plan_approval":
            raise InvalidPipelineTransitionError(
                f"Cannot reject plan: pipeline is '{pipeline.status}', "
                f"expected 'awaiting_plan_approval'"
            )

        pipeline.status = "draft"
        if feedback:
            meta = pipeline.pipeline_metadata or {}
            rejections = meta.get("plan_rejections", [])
            rejections.append({
                "feedback": feedback,
                "actor_id": str(actor_id) if actor_id else None,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            pipeline.pipeline_metadata = {**meta, "plan_rejections": rejections}
            flag_modified(pipeline, "pipeline_metadata")

        await self.events.append(
            stream_id=f"pipeline:{pipeline_id}",
            event_type=PIPELINE_PLAN_REJECTED,
            data={
                "pipeline_id": str(pipeline_id),
                "feedback": feedback,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        await self.db.commit()
        return pipeline

    # ─── Task graph ──────────────────────────────────────

    async def set_task_graph(
        self, pipeline_id: uuid.UUID, task_graph: dict
    ) -> Pipeline:
        """Store the task graph and create PipelineTask rows from it."""
        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        pipeline.task_graph = task_graph
        flag_modified(pipeline, "task_graph")

        # Create PipelineTask rows from the task_graph
        tasks_data = task_graph.get("tasks", [])
        for i, t in enumerate(tasks_data):
            ptask = PipelineTask(
                pipeline_id=pipeline_id,
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
        return pipeline

    # ─── Cost tracking ───────────────────────────────────

    async def update_cost(
        self, pipeline_id: uuid.UUID, cost_delta: float
    ) -> Pipeline:
        """Add cost to the pipeline's running total."""
        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        pipeline.actual_cost_usd = float(pipeline.actual_cost_usd) + cost_delta
        await self.db.commit()
        return pipeline
