"""Model router — intelligent model selection based on role and budget.

Selects the appropriate Claude model for each agent role, with automatic
downgrade when budget pressure exceeds a threshold. This prevents expensive
model usage from draining the pipeline budget on later tasks.

Learn: The router uses a simple profile-based strategy. Each role has a
default and fallback model. Budget pressure (actual/limit ratio) determines
when to downgrade. The "quality" strategy always uses the default, while
"budget" always uses the fallback.
"""

import logging
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import Pipeline

logger = logging.getLogger("openclaw.services.model_router")


# ═══════════════════════════════════════════════════════════
# Model Profiles
# ═══════════════════════════════════════════════════════════

MODEL_PROFILES: dict[str, dict[str, str]] = {
    "planner": {
        "default": "claude-opus-4-20250514",
        "fallback": "claude-sonnet-4-20250514",
    },
    "engineer": {
        "default": "claude-sonnet-4-20250514",
        "fallback": "claude-haiku-4-20250514",
    },
    "reviewer": {
        "default": "claude-sonnet-4-20250514",
        "fallback": "claude-haiku-4-20250514",
    },
    "summarizer": {
        "default": "claude-haiku-4-20250514",
        "fallback": "claude-haiku-4-20250514",
    },
}

BUDGET_PRESSURE_THRESHOLD: float = 0.90

# Approximate cost per 1M tokens (input/output)
MODEL_COSTS: dict[str, dict[str, float]] = {
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-20250514": {"input": 0.80, "output": 4.0},
}


class ModelRouter:
    """Select the appropriate model for a given role and budget context."""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

    async def select_model(
        self,
        role: str,
        pipeline_id: Optional[uuid.UUID] = None,
        strategy: str = "default",
    ) -> str:
        """Select model based on role + budget pressure.

        Args:
            role: Agent role (planner, engineer, reviewer, summarizer)
            pipeline_id: Optional pipeline ID for budget-aware selection
            strategy: "default" (auto), "budget" (always cheap), "quality" (always best)

        Returns the model name string.
        """
        profile = MODEL_PROFILES.get(role, MODEL_PROFILES["engineer"])

        if strategy == "quality":
            model = profile["default"]
            logger.info(
                "Quality strategy: selected %s for role=%s", model, role
            )
            return model

        if strategy == "budget":
            model = profile["fallback"]
            logger.info(
                "Budget strategy: selected %s for role=%s", model, role
            )
            return model

        # Default strategy: check budget pressure
        if pipeline_id and self.db:
            pressure = await self._get_budget_pressure(pipeline_id)
            if pressure >= BUDGET_PRESSURE_THRESHOLD:
                model = profile["fallback"]
                logger.info(
                    "Budget pressure %.1f%% >= %.0f%% threshold: "
                    "downgrading %s → %s for role=%s",
                    pressure * 100,
                    BUDGET_PRESSURE_THRESHOLD * 100,
                    profile["default"],
                    model,
                    role,
                )
                return model

        model = profile["default"]
        logger.debug("Selected %s for role=%s", model, role)
        return model

    async def _get_budget_pressure(self, pipeline_id: uuid.UUID) -> float:
        """Return 0.0-1.0 budget usage ratio."""
        if not self.db:
            return 0.0

        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            return 0.0

        limit = float(pipeline.budget_limit_usd)
        if limit <= 0:
            return 0.0

        actual = float(pipeline.actual_cost_usd)
        return min(actual / limit, 1.0)

    @staticmethod
    def get_cost_per_token(model: str) -> dict[str, float]:
        """Return approximate cost per 1M tokens {input, output}."""
        return MODEL_COSTS.get(
            model, {"input": 3.0, "output": 15.0}
        )
