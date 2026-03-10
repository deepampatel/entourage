"""Tests for PlannerService — intent decomposition into TaskGraph.

Uses mocked Anthropic API to test the planner without actual API calls.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.services.planner_service import (
    COMPLEXITY_COST_ESTIMATE,
    PlannerService,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Planner Org", "slug": "planner-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Planner Team", "slug": "planner-team"},
    )
    return resp.json()


@pytest.fixture
async def draft_pipeline(client, team):
    """A pipeline in draft status ready for planning."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/pipelines",
        json={
            "title": "Add search feature",
            "intent": "Add full-text search with Elasticsearch integration",
            "budget_limit_usd": 10.0,
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _mock_claude_response(tasks):
    """Build a mock Anthropic API response with tool_use."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "create_task_graph"
    tool_block.input = {"tasks": tasks}

    response = MagicMock()
    response.content = [tool_block]
    return response


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cost_estimation():
    """Cost estimation returns expected values based on complexity."""
    planner = PlannerService.__new__(PlannerService)
    task_graph = {
        "tasks": [
            {"complexity": "S"},
            {"complexity": "M"},
            {"complexity": "L"},
            {"complexity": "XL"},
        ]
    }
    cost = planner._estimate_cost(task_graph)
    expected = (
        COMPLEXITY_COST_ESTIMATE["S"]
        + COMPLEXITY_COST_ESTIMATE["M"]
        + COMPLEXITY_COST_ESTIMATE["L"]
        + COMPLEXITY_COST_ESTIMATE["XL"]
    )
    assert cost == round(expected, 2)


@pytest.mark.asyncio
async def test_extract_task_graph():
    """Extracts task_graph from Claude's tool_use response."""
    planner = PlannerService.__new__(PlannerService)
    tasks = [
        {
            "title": "Setup models",
            "description": "Create DB models",
            "complexity": "M",
            "assigned_role": "engineer",
            "dependencies": [],
        }
    ]
    response = _mock_claude_response(tasks)
    result = planner._extract_task_graph(response)
    assert result["tasks"] == tasks


@pytest.mark.asyncio
async def test_extract_task_graph_missing_tool_call():
    """Raises ValueError if Claude doesn't return a tool call."""
    planner = PlannerService.__new__(PlannerService)

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Here is the plan..."

    response = MagicMock()
    response.content = [text_block]

    with pytest.raises(ValueError, match="did not return"):
        planner._extract_task_graph(response)


@pytest.mark.asyncio
async def test_build_planning_prompt():
    """Planning prompt includes intent and guidelines."""
    planner = PlannerService.__new__(PlannerService)
    prompt = planner._build_planning_prompt(
        intent="Add user authentication with OAuth2",
        conventions=[{"name": "Style", "content": "Use Black formatter"}],
    )
    assert "Add user authentication with OAuth2" in prompt
    assert "Use Black formatter" in prompt
    assert "create_task_graph" in prompt


@pytest.mark.asyncio
async def test_plan_generates_task_graph(client, draft_pipeline, db_session):
    """PlannerService.plan() generates a task graph and transitions pipeline."""
    pipeline_id = uuid.UUID(draft_pipeline["id"])

    mock_tasks = [
        {
            "title": "Set up Elasticsearch client",
            "description": "Install and configure ES client",
            "complexity": "S",
            "assigned_role": "engineer",
            "dependencies": [],
            "integration_hints": ["Provides ES client for task 1"],
        },
        {
            "title": "Implement search API endpoint",
            "description": "Create /api/search endpoint",
            "complexity": "M",
            "assigned_role": "engineer",
            "dependencies": [0],
            "integration_hints": [],
        },
    ]

    mock_response = _mock_claude_response(mock_tasks)

    with patch(
        "openclaw.services.planner_service.settings"
    ) as mock_settings:
        mock_settings.anthropic_api_key = "test-key-for-mocking"

        with patch(
            "openclaw.services.planner_service.anthropic.AsyncAnthropic"
        ) as MockAnthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            MockAnthropic.return_value = mock_client

            planner = PlannerService(db_session)
            result = await planner.plan(pipeline_id)

    assert "tasks" in result
    assert len(result["tasks"]) == 2
    assert result["tasks"][0]["title"] == "Set up Elasticsearch client"
    assert result["estimated_cost_usd"] == round(
        COMPLEXITY_COST_ESTIMATE["S"] + COMPLEXITY_COST_ESTIMATE["M"], 2
    )

    # Verify pipeline transitioned to awaiting_plan_approval
    resp = await client.get(f"/api/v1/pipelines/{draft_pipeline['id']}")
    assert resp.json()["status"] == "awaiting_plan_approval"

    # Verify pipeline tasks were created
    tasks_resp = await client.get(
        f"/api/v1/pipelines/{draft_pipeline['id']}/tasks"
    )
    tasks = tasks_resp.json()
    assert len(tasks) == 2
    assert tasks[0]["title"] == "Set up Elasticsearch client"
    assert tasks[1]["dependencies"] == [0]
