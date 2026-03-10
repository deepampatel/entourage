"""Tests for ExecutionLoop — serial pipeline task dispatch.

Tests the execution loop's task ordering, dependency resolution,
failure handling, and budget enforcement.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.execution_loop import ExecutionLoop


def _make_session_factory(db_session):
    """Create a mock async_session_factory that yields the test db_session.

    Learn: ExecutionLoop.run() bypasses FastAPI DI and directly imports
    async_session_factory. In tests, we patch it to return the test session
    so the loop operates within the test's savepoint transaction.
    """
    @asynccontextmanager
    async def factory():
        yield db_session
    return factory


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Loop Org", "slug": "loop-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Loop Team", "slug": "loop-team"},
    )
    return resp.json()


@pytest.fixture
async def engineer_agent(client, team):
    """Create an idle engineer agent."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/agents",
        json={"name": "EngBot", "role": "engineer"},
    )
    return resp.json()


@pytest.fixture
async def executing_pipeline(client, team):
    """Pipeline in 'executing' state with a task graph."""
    # Create pipeline
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/pipelines",
        json={
            "title": "Build feature X",
            "intent": "Implement feature X end to end",
            "budget_limit_usd": 20.0,
        },
    )
    pipeline = resp.json()
    pid = pipeline["id"]

    # Transition to planning
    await client.post(
        f"/api/v1/pipelines/{pid}/status", json={"status": "planning"}
    )

    # Set task graph with 2 tasks (task 1 depends on task 0)
    await client.post(
        f"/api/v1/pipelines/{pid}/task-graph",
        json={
            "task_graph": {
                "tasks": [
                    {
                        "title": "Create models",
                        "description": "Add DB models for feature X",
                        "complexity": "S",
                        "assigned_role": "engineer",
                        "dependencies": [],
                    },
                    {
                        "title": "Create API endpoints",
                        "description": "Add REST endpoints for feature X",
                        "complexity": "M",
                        "assigned_role": "engineer",
                        "dependencies": [0],
                    },
                ]
            }
        },
    )

    # Transition to awaiting_plan_approval → executing
    await client.post(
        f"/api/v1/pipelines/{pid}/status",
        json={"status": "awaiting_plan_approval"},
    )
    await client.post(f"/api/v1/pipelines/{pid}/approve-plan", json={})

    # Re-fetch
    resp = await client.get(f"/api/v1/pipelines/{pid}")
    return resp.json()


# ═══════════════════════════════════════════════════════════
# Unit tests — dependency resolution
# ═══════════════════════════════════════════════════════════


def test_find_ready_task_no_deps():
    """First task with no deps is ready."""
    from unittest.mock import MagicMock

    loop = ExecutionLoop()

    task0 = MagicMock()
    task0.id = 1
    task0.status = "todo"
    task0.dependencies = []

    task1 = MagicMock()
    task1.id = 2
    task1.status = "todo"
    task1.dependencies = [0]

    ready = loop._find_ready_task([task0, task1])
    assert ready == task0


def test_find_ready_task_with_deps_met():
    """Task with deps is ready when deps are done."""
    from unittest.mock import MagicMock

    loop = ExecutionLoop()

    task0 = MagicMock()
    task0.id = 1
    task0.status = "done"
    task0.dependencies = []

    task1 = MagicMock()
    task1.id = 2
    task1.status = "todo"
    task1.dependencies = [0]

    ready = loop._find_ready_task([task0, task1])
    assert ready == task1


def test_find_ready_task_blocked():
    """No task is ready when all deps are unmet."""
    from unittest.mock import MagicMock

    loop = ExecutionLoop()

    task0 = MagicMock()
    task0.id = 1
    task0.status = "in_progress"
    task0.dependencies = []

    task1 = MagicMock()
    task1.id = 2
    task1.status = "todo"
    task1.dependencies = [0]

    ready = loop._find_ready_task([task0, task1])
    assert ready is None


def test_find_ready_task_all_done():
    """No ready task when all tasks are done."""
    from unittest.mock import MagicMock

    loop = ExecutionLoop()

    task0 = MagicMock()
    task0.id = 1
    task0.status = "done"
    task0.dependencies = []

    ready = loop._find_ready_task([task0])
    assert ready is None


# ═══════════════════════════════════════════════════════════
# Integration tests — full loop
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execution_loop_completes(
    client, executing_pipeline, engineer_agent, db_session
):
    """Execution loop runs all tasks and transitions to reviewing."""
    pid = uuid.UUID(executing_pipeline["id"])

    with patch.object(
        ExecutionLoop, "_run_task", new_callable=AsyncMock, return_value=True
    ), patch(
        "openclaw.services.execution_loop.async_session_factory",
        _make_session_factory(db_session),
    ), patch.object(
        ExecutionLoop, "_publish_event", new_callable=AsyncMock,
    ), patch.object(
        ExecutionLoop, "_run_sandbox_if_configured",
        new_callable=AsyncMock, return_value=None,
    ), patch(
        "openclaw.services.execution_loop.settings"
    ) as mock_settings:
        mock_settings.task_polling_interval_seconds = 0
        mock_settings.max_concurrent_pipeline_tasks = 1
        mock_settings.max_task_retries = 0
        mock_settings.sandbox_enabled = False

        loop = ExecutionLoop()
        result = await loop.run(pid)

    assert result["status"] == "reviewing"
    assert result["reason"] == "All tasks completed"

    # Verify pipeline status
    resp = await client.get(f"/api/v1/pipelines/{executing_pipeline['id']}")
    assert resp.json()["status"] == "reviewing"

    # Verify tasks are all done
    tasks_resp = await client.get(
        f"/api/v1/pipelines/{executing_pipeline['id']}/tasks"
    )
    tasks = tasks_resp.json()
    assert all(t["status"] == "done" for t in tasks)


@pytest.mark.asyncio
async def test_execution_loop_task_failure(
    client, executing_pipeline, engineer_agent, db_session
):
    """If a task fails, the pipeline is marked failed."""
    pid = uuid.UUID(executing_pipeline["id"])

    # First task succeeds, second fails
    call_count = 0

    async def _mock_run_task(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return call_count <= 1  # First returns True, second False

    with patch.object(
        ExecutionLoop, "_run_task", side_effect=_mock_run_task
    ), patch(
        "openclaw.services.execution_loop.async_session_factory",
        _make_session_factory(db_session),
    ), patch.object(
        ExecutionLoop, "_publish_event", new_callable=AsyncMock,
    ), patch.object(
        ExecutionLoop, "_run_sandbox_if_configured",
        new_callable=AsyncMock, return_value=None,
    ), patch(
        "openclaw.services.execution_loop.settings"
    ) as mock_settings:
        mock_settings.task_polling_interval_seconds = 0
        mock_settings.max_concurrent_pipeline_tasks = 1
        mock_settings.max_task_retries = 0
        mock_settings.sandbox_enabled = False

        loop = ExecutionLoop()
        result = await loop.run(pid)

    assert result["status"] == "failed"

    # Verify pipeline status
    resp = await client.get(f"/api/v1/pipelines/{executing_pipeline['id']}")
    assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_execution_loop_no_idle_agent(
    client, executing_pipeline, db_session
):
    """Loop stops if pipeline is no longer executing (e.g. cancelled while waiting)."""
    pid = uuid.UUID(executing_pipeline["id"])

    call_count = 0

    async def _cancel_after_first(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            # Cancel the pipeline to exit the loop
            await client.post(
                f"/api/v1/pipelines/{executing_pipeline['id']}/status",
                json={"status": "cancelled"},
            )
        return []  # No idle agents

    with patch.object(
        ExecutionLoop,
        "_find_idle_agents",
        side_effect=_cancel_after_first,
    ), patch(
        "openclaw.services.execution_loop.async_session_factory",
        _make_session_factory(db_session),
    ), patch.object(
        ExecutionLoop, "_publish_event", new_callable=AsyncMock,
    ), patch(
        "openclaw.services.execution_loop.settings"
    ) as mock_settings:
        mock_settings.task_polling_interval_seconds = 0
        mock_settings.max_concurrent_pipeline_tasks = 1
        mock_settings.max_task_retries = 0
        mock_settings.sandbox_enabled = False

        loop = ExecutionLoop()
        result = await loop.run(pid)

    # Pipeline should have been cancelled
    assert result["status"] in ("cancelled", "failed")
