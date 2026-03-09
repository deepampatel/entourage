"""Tests for ModelRouter service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw.services.model_router import (
    BUDGET_PRESSURE_THRESHOLD,
    MODEL_PROFILES,
    ModelRouter,
)


class TestSelectModel:
    @pytest.mark.asyncio
    async def test_default_strategy_engineer(self):
        """Default strategy uses the default model for the role."""
        router = ModelRouter()
        model = await router.select_model("engineer")
        assert model == MODEL_PROFILES["engineer"]["default"]
        assert model == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_default_strategy_planner(self):
        """Planner gets Opus by default."""
        router = ModelRouter()
        model = await router.select_model("planner")
        assert model == "claude-opus-4-20250514"

    @pytest.mark.asyncio
    async def test_quality_strategy(self):
        """Quality strategy always uses default model."""
        router = ModelRouter()
        model = await router.select_model("engineer", strategy="quality")
        assert model == MODEL_PROFILES["engineer"]["default"]

    @pytest.mark.asyncio
    async def test_budget_strategy(self):
        """Budget strategy always uses fallback model."""
        router = ModelRouter()
        model = await router.select_model("engineer", strategy="budget")
        assert model == MODEL_PROFILES["engineer"]["fallback"]
        assert model == "claude-haiku-4-20250514"

    @pytest.mark.asyncio
    async def test_budget_pressure_downgrade(self):
        """When budget pressure exceeds threshold, auto-downgrade."""
        mock_db = AsyncMock()
        mock_pipeline = MagicMock()
        mock_pipeline.budget_limit_usd = 10.0
        mock_pipeline.actual_cost_usd = 9.5  # 95% used
        mock_db.get = AsyncMock(return_value=mock_pipeline)

        router = ModelRouter(db=mock_db)
        model = await router.select_model(
            "engineer",
            pipeline_id="test-id",
        )
        assert model == MODEL_PROFILES["engineer"]["fallback"]

    @pytest.mark.asyncio
    async def test_no_downgrade_below_threshold(self):
        """When budget pressure is below threshold, use default."""
        mock_db = AsyncMock()
        mock_pipeline = MagicMock()
        mock_pipeline.budget_limit_usd = 10.0
        mock_pipeline.actual_cost_usd = 5.0  # 50% used
        mock_db.get = AsyncMock(return_value=mock_pipeline)

        router = ModelRouter(db=mock_db)
        model = await router.select_model(
            "engineer",
            pipeline_id="test-id",
        )
        assert model == MODEL_PROFILES["engineer"]["default"]

    @pytest.mark.asyncio
    async def test_unknown_role_defaults_to_engineer(self):
        """Unknown roles fall back to engineer profile."""
        router = ModelRouter()
        model = await router.select_model("unknown_role")
        assert model == MODEL_PROFILES["engineer"]["default"]

    @pytest.mark.asyncio
    async def test_summarizer_role(self):
        """Summarizer uses Haiku for both default and fallback."""
        router = ModelRouter()
        model = await router.select_model("summarizer")
        assert model == "claude-haiku-4-20250514"

    @pytest.mark.asyncio
    async def test_no_db_skips_budget_check(self):
        """Without DB, budget check is skipped."""
        router = ModelRouter(db=None)
        model = await router.select_model("engineer", pipeline_id="test-id")
        assert model == MODEL_PROFILES["engineer"]["default"]


class TestGetBudgetPressure:
    @pytest.mark.asyncio
    async def test_zero_limit(self):
        """Zero budget limit returns 0.0 pressure."""
        mock_db = AsyncMock()
        mock_pipeline = MagicMock()
        mock_pipeline.budget_limit_usd = 0
        mock_pipeline.actual_cost_usd = 5.0
        mock_db.get = AsyncMock(return_value=mock_pipeline)

        router = ModelRouter(db=mock_db)
        pressure = await router._get_budget_pressure("test-id")
        assert pressure == 0.0

    @pytest.mark.asyncio
    async def test_pipeline_not_found(self):
        """Missing pipeline returns 0.0 pressure."""
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        router = ModelRouter(db=mock_db)
        pressure = await router._get_budget_pressure("test-id")
        assert pressure == 0.0

    @pytest.mark.asyncio
    async def test_caps_at_one(self):
        """Pressure is capped at 1.0 even if over budget."""
        mock_db = AsyncMock()
        mock_pipeline = MagicMock()
        mock_pipeline.budget_limit_usd = 10.0
        mock_pipeline.actual_cost_usd = 15.0  # Over budget
        mock_db.get = AsyncMock(return_value=mock_pipeline)

        router = ModelRouter(db=mock_db)
        pressure = await router._get_budget_pressure("test-id")
        assert pressure == 1.0


class TestGetCostPerToken:
    def test_known_model(self):
        costs = ModelRouter.get_cost_per_token("claude-sonnet-4-20250514")
        assert "input" in costs
        assert "output" in costs
        assert costs["input"] == 3.0

    def test_unknown_model_defaults(self):
        costs = ModelRouter.get_cost_per_token("unknown-model")
        assert costs["input"] == 3.0
        assert costs["output"] == 15.0
