"""Pipeline budget service — per-pipeline cost tracking and enforcement.

Each pipeline gets a BudgetLedger. As agents work, cost entries are
recorded and the running total is updated. Warnings at 80%,
hard stop at 100%.
"""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import BudgetEntry, BudgetLedger
from openclaw.events.store import EventStore
from openclaw.events.types import PIPELINE_BUDGET_EXCEEDED, PIPELINE_BUDGET_WARNING
from openclaw.services.session_service import MODEL_PRICING, DEFAULT_PRICING


class PipelineBudgetExceededError(Exception):
    """Raised when a pipeline's budget is exceeded."""
    pass


class PipelineBudgetService:
    """Cost tracking and enforcement for pipelines."""

    WARN_THRESHOLD = 0.80  # 80% of budget

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)

    async def get_ledger(self, pipeline_id: uuid.UUID) -> Optional[BudgetLedger]:
        """Get the budget ledger for a pipeline."""
        result = await self.db.execute(
            select(BudgetLedger).where(
                BudgetLedger.pipeline_id == pipeline_id
            )
        )
        return result.scalars().first()

    async def add_cost(
        self,
        pipeline_id: uuid.UUID,
        model: str,
        input_tokens: int,
        output_tokens: int,
        pipeline_task_id: Optional[int] = None,
        agent_id: Optional[uuid.UUID] = None,
    ) -> BudgetLedger:
        """Record a cost entry and update the running total.

        Emits warning at 80%, raises PipelineBudgetExceededError at 100%.
        """
        ledger = await self.get_ledger(pipeline_id)
        if not ledger:
            raise ValueError(f"No budget ledger for pipeline {pipeline_id}")

        # Compute cost
        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
        cost = (
            input_tokens * pricing["input"] / 1_000_000
            + output_tokens * pricing["output"] / 1_000_000
        )

        # Create entry
        entry = BudgetEntry(
            ledger_id=ledger.id,
            pipeline_id=pipeline_id,
            pipeline_task_id=pipeline_task_id,
            agent_id=agent_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.db.add(entry)

        # Update ledger running total
        new_actual = float(ledger.actual_cost_usd) + cost
        ledger.actual_cost_usd = new_actual
        limit = float(ledger.budget_limit_usd)

        # Check thresholds
        if limit > 0:
            usage_ratio = new_actual / limit

            if usage_ratio >= 1.0:
                ledger.status = "exceeded"
                await self.events.append(
                    stream_id=f"pipeline:{pipeline_id}",
                    event_type=PIPELINE_BUDGET_EXCEEDED,
                    data={
                        "pipeline_id": str(pipeline_id),
                        "actual": new_actual,
                        "limit": limit,
                    },
                )
                await self.db.commit()
                raise PipelineBudgetExceededError(
                    f"Pipeline {pipeline_id} exceeded budget: "
                    f"${new_actual:.4f} / ${limit:.4f}"
                )

            if usage_ratio >= self.WARN_THRESHOLD and ledger.status == "ok":
                ledger.status = "warn"
                await self.events.append(
                    stream_id=f"pipeline:{pipeline_id}",
                    event_type=PIPELINE_BUDGET_WARNING,
                    data={
                        "pipeline_id": str(pipeline_id),
                        "actual": new_actual,
                        "limit": limit,
                        "usage_ratio": usage_ratio,
                    },
                )

        await self.db.commit()
        return ledger

    async def check_budget(self, pipeline_id: uuid.UUID) -> dict:
        """Check budget status without recording cost."""
        ledger = await self.get_ledger(pipeline_id)
        if not ledger:
            return {"within_budget": True, "actual": 0, "limit": 0, "percent_used": 0}

        actual = float(ledger.actual_cost_usd)
        limit = float(ledger.budget_limit_usd)
        percent = (actual / limit * 100) if limit > 0 else 0

        return {
            "within_budget": actual < limit,
            "actual": actual,
            "limit": limit,
            "percent_used": round(percent, 1),
            "status": ledger.status,
        }

    async def list_entries(
        self, pipeline_id: uuid.UUID, limit: int = 100
    ) -> list[BudgetEntry]:
        """List cost entries for a pipeline."""
        ledger = await self.get_ledger(pipeline_id)
        if not ledger:
            return []

        result = await self.db.execute(
            select(BudgetEntry)
            .where(BudgetEntry.ledger_id == ledger.id)
            .order_by(BudgetEntry.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_estimate(
        self, pipeline_id: uuid.UUID, estimated_cost: float
    ) -> BudgetLedger:
        """Set the estimated cost for the pipeline."""
        ledger = await self.get_ledger(pipeline_id)
        if not ledger:
            raise ValueError(f"No budget ledger for pipeline {pipeline_id}")

        ledger.estimated_cost_usd = estimated_cost
        await self.db.commit()
        return ledger
