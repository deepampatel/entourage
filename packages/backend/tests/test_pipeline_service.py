"""Phase 12 tests — Pipeline CRUD, state machine, budget tracking.

Tests the Pipeline service layer: creation, status transitions,
plan approval/rejection, task graph storage, and budget enforcement.
"""

import pytest


# ═══════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Pipeline Org", "slug": "pipeline-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Pipeline Team", "slug": "pipeline-team"},
    )
    return resp.json()


@pytest.fixture
async def pipeline(client, team):
    """Create a pipeline and return its data."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/pipelines",
        json={
            "title": "Add OAuth2 login",
            "intent": "Add Google OAuth2 login with session management",
            "budget_limit_usd": 5.0,
        },
    )
    assert resp.status_code == 201
    return resp.json()


# ═══════════════════════════════════════════════════════════
# Pipeline CRUD
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_pipeline(client, team):
    """POST /teams/:id/pipelines creates a pipeline in draft status."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/pipelines",
        json={
            "title": "Add user profiles",
            "intent": "Add user profile pages with avatar upload",
            "budget_limit_usd": 8.0,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Add user profiles"
    assert data["intent"] == "Add user profile pages with avatar upload"
    assert data["status"] == "draft"
    assert data["budget_limit_usd"] == 8.0
    assert data["actual_cost_usd"] == 0
    assert data["estimated_cost_usd"] == 0
    assert data["team_id"] == team["id"]


@pytest.mark.asyncio
async def test_list_pipelines(client, team, pipeline):
    """GET /teams/:id/pipelines lists pipelines for a team."""
    resp = await client.get(f"/api/v1/teams/{team['id']}/pipelines")
    assert resp.status_code == 200
    pipelines = resp.json()
    assert len(pipelines) >= 1
    assert any(p["id"] == pipeline["id"] for p in pipelines)


@pytest.mark.asyncio
async def test_get_pipeline(client, pipeline):
    """GET /pipelines/:id returns pipeline detail."""
    resp = await client.get(f"/api/v1/pipelines/{pipeline['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == pipeline["id"]
    assert data["title"] == "Add OAuth2 login"


@pytest.mark.asyncio
async def test_get_pipeline_not_found(client):
    """GET /pipelines/:id returns 404 for unknown ID."""
    resp = await client.get(
        "/api/v1/pipelines/00000000-0000-0000-0000-000000000099"
    )
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_valid_transition_draft_to_planning(client, pipeline):
    """Pipeline can transition from draft to planning."""
    resp = await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "planning"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "planning"


@pytest.mark.asyncio
async def test_invalid_transition_draft_to_executing(client, pipeline):
    """Pipeline cannot skip from draft to executing."""
    resp = await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "executing"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_transition_to_cancelled(client, pipeline):
    """Pipeline can be cancelled from draft."""
    resp = await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "cancelled"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelled_is_terminal(client, pipeline):
    """Cancelled pipelines cannot transition to any state."""
    await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "cancelled"},
    )
    resp = await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "draft"},
    )
    assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════
# Plan Approval / Rejection
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def pipeline_awaiting_approval(client, pipeline):
    """Pipeline in awaiting_plan_approval state with a task graph."""
    # Transition to planning
    await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "planning"},
    )
    # Set a task graph (simulating planner output)
    await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/task-graph",
        json={
            "task_graph": {
                "tasks": [
                    {
                        "title": "Set up OAuth config",
                        "description": "Configure OAuth credentials",
                        "complexity": "S",
                        "assigned_role": "engineer",
                        "dependencies": [],
                    },
                    {
                        "title": "Implement callback handler",
                        "description": "OAuth callback endpoint",
                        "complexity": "M",
                        "assigned_role": "engineer",
                        "dependencies": [1],
                    },
                ]
            }
        },
    )
    # Transition to awaiting_plan_approval
    await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/status",
        json={"status": "awaiting_plan_approval"},
    )
    # Re-fetch
    resp = await client.get(f"/api/v1/pipelines/{pipeline['id']}")
    return resp.json()


@pytest.mark.asyncio
async def test_approve_plan(client, pipeline_awaiting_approval):
    """Approving a plan transitions to executing."""
    pid = pipeline_awaiting_approval["id"]
    resp = await client.post(f"/api/v1/pipelines/{pid}/approve-plan", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "executing"


@pytest.mark.asyncio
async def test_reject_plan(client, pipeline_awaiting_approval):
    """Rejecting a plan transitions back to draft with feedback."""
    pid = pipeline_awaiting_approval["id"]
    resp = await client.post(
        f"/api/v1/pipelines/{pid}/reject-plan",
        json={"feedback": "Split auth into separate tasks"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_approve_wrong_status(client, pipeline):
    """Cannot approve plan when not in awaiting_plan_approval."""
    resp = await client.post(
        f"/api/v1/pipelines/{pipeline['id']}/approve-plan", json={}
    )
    assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════
# Task Graph
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_set_task_graph_creates_pipeline_tasks(client, pipeline):
    """Setting a task graph creates PipelineTask rows."""
    pid = pipeline["id"]
    # Transition to planning
    await client.post(
        f"/api/v1/pipelines/{pid}/status", json={"status": "planning"}
    )
    # Set task graph
    resp = await client.post(
        f"/api/v1/pipelines/{pid}/task-graph",
        json={
            "task_graph": {
                "tasks": [
                    {
                        "title": "Task A",
                        "description": "First task",
                        "complexity": "S",
                        "assigned_role": "engineer",
                    },
                    {
                        "title": "Task B",
                        "description": "Second task",
                        "complexity": "M",
                        "assigned_role": "engineer",
                        "dependencies": [1],
                    },
                    {
                        "title": "Review",
                        "description": "Code review",
                        "complexity": "S",
                        "assigned_role": "reviewer",
                        "dependencies": [1, 2],
                    },
                ]
            }
        },
    )
    assert resp.status_code == 200

    # Verify tasks were created
    tasks_resp = await client.get(f"/api/v1/pipelines/{pid}/tasks")
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()
    assert len(tasks) == 3
    assert tasks[0]["title"] == "Task A"
    assert tasks[0]["complexity"] == "S"
    assert tasks[1]["dependencies"] == [1]
    assert tasks[2]["assigned_role"] == "reviewer"


# ═══════════════════════════════════════════════════════════
# Budget
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_budget_ledger_created_with_pipeline(client, pipeline):
    """A budget ledger is created automatically when a pipeline is created."""
    resp = await client.get(f"/api/v1/pipelines/{pipeline['id']}/budget")
    assert resp.status_code == 200
    budget = resp.json()
    assert budget["budget_limit_usd"] == 5.0
    assert budget["actual_cost_usd"] == 0
    assert budget["status"] == "ok"


@pytest.mark.asyncio
async def test_list_pipelines_with_status_filter(client, team, pipeline):
    """GET /teams/:id/pipelines?status=draft filters by status."""
    resp = await client.get(
        f"/api/v1/teams/{team['id']}/pipelines?status=draft"
    )
    assert resp.status_code == 200
    pipelines = resp.json()
    assert all(p["status"] == "draft" for p in pipelines)
