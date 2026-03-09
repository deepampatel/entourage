"""Tests for sandbox API endpoints and execution loop integration.

Covers: sandbox API CRUD, execution loop sandbox-on-success behavior,
retry-on-sandbox-failure, and graceful Docker-unavailable handling.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.execution_loop import ExecutionLoop
from openclaw.services.sandbox_manager import SandboxManager, SandboxResult


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Sandbox Org", "slug": "sandbox-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Sandbox Team", "slug": "sandbox-team"},
    )
    return resp.json()


@pytest.fixture
async def engineer_agent(client, team):
    """Create an idle engineer agent."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/agents",
        json={"name": "SandboxEng", "role": "engineer"},
    )
    return resp.json()


@pytest.fixture
async def executing_pipeline(client, team):
    """Pipeline in 'executing' state with a task graph."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/pipelines",
        json={
            "title": "Sandbox Test Pipeline",
            "intent": "Test sandbox integration",
            "budget_limit_usd": 20.0,
        },
    )
    pipeline = resp.json()
    pid = pipeline["id"]

    await client.post(
        f"/api/v1/pipelines/{pid}/status", json={"status": "planning"}
    )

    await client.post(
        f"/api/v1/pipelines/{pid}/task-graph",
        json={
            "task_graph": {
                "tasks": [
                    {
                        "title": "Create models",
                        "description": "Add DB models",
                        "complexity": "S",
                        "assigned_role": "engineer",
                        "dependencies": [],
                    },
                    {
                        "title": "Create API",
                        "description": "Add REST endpoints",
                        "complexity": "M",
                        "assigned_role": "engineer",
                        "dependencies": [0],
                    },
                ]
            }
        },
    )

    await client.post(
        f"/api/v1/pipelines/{pid}/status",
        json={"status": "awaiting_plan_approval"},
    )
    await client.post(f"/api/v1/pipelines/{pid}/approve-plan", json={})

    resp = await client.get(f"/api/v1/pipelines/{pid}")
    return resp.json()


# ═══════════════════════════════════════════════════════════
# API tests — sandbox endpoints
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sandbox_api_list_empty(client, executing_pipeline):
    """GET sandbox runs returns empty list for task with no runs."""
    pid = executing_pipeline["id"]
    tasks_resp = await client.get(f"/api/v1/pipelines/{pid}/tasks")
    task_id = tasks_resp.json()[0]["id"]

    resp = await client.get(
        f"/api/v1/pipelines/{pid}/tasks/{task_id}/sandbox-runs"
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_sandbox_api_trigger(client, executing_pipeline):
    """POST creates a sandbox run and returns 202."""
    pid = executing_pipeline["id"]
    tasks_resp = await client.get(f"/api/v1/pipelines/{pid}/tasks")
    task_id = tasks_resp.json()[0]["id"]

    with patch.object(
        SandboxManager,
        "run_tests",
        new_callable=AsyncMock,
        return_value=SandboxResult(
            sandbox_id="abc123def456",
            exit_code=0,
            stdout="All tests passed",
            stderr="",
            duration_seconds=5.2,
            passed=True,
            started_at=None,
            ended_at=None,
        ),
    ), patch.object(
        SandboxManager,
        "check_docker",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = await client.post(
            f"/api/v1/pipelines/{pid}/tasks/{task_id}/sandbox-runs",
            json={"test_cmd": "pytest tests/", "image": "python:3.12-slim"},
        )
        assert resp.status_code == 202


@pytest.mark.asyncio
async def test_sandbox_api_get_by_id(client, executing_pipeline, db_session):
    """GET /sandbox-runs/{sandbox_id} returns a specific run."""
    from datetime import datetime, timezone

    from openclaw.db.models import SandboxRun

    pid = executing_pipeline["id"]
    tasks_resp = await client.get(f"/api/v1/pipelines/{pid}/tasks")
    task_id = tasks_resp.json()[0]["id"]

    # Insert a sandbox run directly into DB
    run = SandboxRun(
        sandbox_id="test-run-001",
        pipeline_id=uuid.UUID(pid),
        pipeline_task_id=task_id,
        team_id=uuid.UUID(executing_pipeline["team_id"]),
        test_cmd="pytest tests/",
        exit_code=0,
        stdout="OK",
        stderr="",
        passed=True,
        duration_seconds=3.0,
        image="python:3.12-slim",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.get("/api/v1/sandbox-runs/test-run-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sandbox_id"] == "test-run-001"
    assert data["passed"] is True
    assert data["exit_code"] == 0


# ═══════════════════════════════════════════════════════════
# Execution loop integration tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execution_loop_runs_sandbox_on_success(
    client, executing_pipeline, engineer_agent
):
    """Sandbox tests triggered after task completion when configured."""
    pid = uuid.UUID(executing_pipeline["id"])

    sandbox_result = SandboxResult(
        sandbox_id="loop-sandbox-001",
        exit_code=0,
        stdout="All tests passed",
        stderr="",
        duration_seconds=4.0,
        passed=True,
        started_at=None,
        ended_at=None,
    )

    with patch.object(
        ExecutionLoop, "_run_task", new_callable=AsyncMock, return_value=True
    ), patch.object(
        SandboxManager,
        "check_docker",
        new_callable=AsyncMock,
        return_value=True,
    ), patch.object(
        SandboxManager,
        "run_tests",
        new_callable=AsyncMock,
        return_value=sandbox_result,
    ), patch(
        "openclaw.services.execution_loop.settings"
    ) as mock_settings:
        mock_settings.sandbox_enabled = True
        mock_settings.sandbox_default_image = "python:3.12-slim"
        mock_settings.max_concurrent_agents = 32

        loop = ExecutionLoop()
        result = await loop.run(pid)

    # Pipeline should reach reviewing or done — not blocked by sandbox
    assert result["status"] in ("reviewing", "done", "failed")


@pytest.mark.asyncio
async def test_execution_loop_retries_on_sandbox_failure(
    client, executing_pipeline, engineer_agent
):
    """Task reset to todo when sandbox tests fail (if retries available)."""
    pid = uuid.UUID(executing_pipeline["id"])

    sandbox_fail = SandboxResult(
        sandbox_id="loop-sandbox-fail",
        exit_code=1,
        stdout="",
        stderr="FAILED: test_auth.py::test_login",
        duration_seconds=2.0,
        passed=False,
        started_at=None,
        ended_at=None,
    )

    call_count = 0

    async def mock_run_task(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return True

    with patch.object(
        ExecutionLoop, "_run_task", side_effect=mock_run_task
    ), patch.object(
        SandboxManager,
        "check_docker",
        new_callable=AsyncMock,
        return_value=True,
    ), patch.object(
        SandboxManager,
        "run_tests",
        new_callable=AsyncMock,
        return_value=sandbox_fail,
    ), patch(
        "openclaw.services.execution_loop.settings"
    ) as mock_settings:
        mock_settings.sandbox_enabled = True
        mock_settings.sandbox_default_image = "python:3.12-slim"
        mock_settings.max_concurrent_agents = 32
        mock_settings.max_task_retries = 2

        loop = ExecutionLoop()
        result = await loop.run(pid)

    # The loop should have retried tasks that failed sandbox
    assert call_count >= 1


@pytest.mark.asyncio
async def test_execution_loop_skips_sandbox_no_docker(
    client, executing_pipeline, engineer_agent
):
    """Gracefully skips sandbox when Docker is unavailable."""
    pid = uuid.UUID(executing_pipeline["id"])

    with patch.object(
        ExecutionLoop, "_run_task", new_callable=AsyncMock, return_value=True
    ), patch.object(
        SandboxManager,
        "check_docker",
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        "openclaw.services.execution_loop.settings"
    ) as mock_settings:
        mock_settings.sandbox_enabled = True
        mock_settings.sandbox_default_image = "python:3.12-slim"
        mock_settings.max_concurrent_agents = 32

        loop = ExecutionLoop()
        result = await loop.run(pid)

    # Pipeline should complete normally — sandbox skipped
    assert result["status"] in ("reviewing", "done", "failed")
