"""Phase 12 tests — Run CRUD, state machine, budget tracking.

Tests the Run service layer: creation, status transitions,
plan approval/rejection, task graph storage, and budget enforcement.
"""

import pytest


# ═══════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Run Org", "slug": "run-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Run Team", "slug": "run-team"},
    )
    return resp.json()


@pytest.fixture
async def run(client, team):
    """Create a run and return its data."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/runs",
        json={
            "title": "Add OAuth2 login",
            "intent": "Add Google OAuth2 login with session management",
            "budget_limit_usd": 5.0,
        },
    )
    assert resp.status_code == 201
    return resp.json()


# ═══════════════════════════════════════════════════════════
# Run CRUD
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_run(client, team):
    """POST /teams/:id/runs creates a run in draft status."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/runs",
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
async def test_list_runs(client, team, run):
    """GET /teams/:id/runs lists runs for a team."""
    resp = await client.get(f"/api/v1/teams/{team['id']}/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1
    assert any(p["id"] == run["id"] for p in runs)


@pytest.mark.asyncio
async def test_get_run(client, run):
    """GET /runs/:id returns run detail."""
    resp = await client.get(f"/api/v1/runs/{run['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run["id"]
    assert data["title"] == "Add OAuth2 login"


@pytest.mark.asyncio
async def test_get_run_not_found(client):
    """GET /runs/:id returns 404 for unknown ID."""
    resp = await client.get(
        "/api/v1/runs/00000000-0000-0000-0000-000000000099"
    )
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_valid_transition_draft_to_planning(client, run):
    """Run can transition from draft to planning."""
    resp = await client.post(
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "planning"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "planning"


@pytest.mark.asyncio
async def test_invalid_transition_draft_to_executing(client, run):
    """Run cannot skip from draft to executing."""
    resp = await client.post(
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "executing"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_transition_to_cancelled(client, run):
    """Run can be cancelled from draft."""
    resp = await client.post(
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "cancelled"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelled_is_terminal(client, run):
    """Cancelled runs cannot transition to any state."""
    await client.post(
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "cancelled"},
    )
    resp = await client.post(
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "draft"},
    )
    assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════
# Plan Approval / Rejection
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def run_awaiting_approval(client, run):
    """Run in awaiting_plan_approval state with a task graph."""
    # Transition to planning
    await client.post(
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "planning"},
    )
    # Set a task graph (simulating planner output)
    await client.post(
        f"/api/v1/runs/{run['id']}/task-graph",
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
        f"/api/v1/runs/{run['id']}/status",
        json={"status": "awaiting_plan_approval"},
    )
    # Re-fetch
    resp = await client.get(f"/api/v1/runs/{run['id']}")
    return resp.json()


@pytest.mark.asyncio
async def test_approve_plan(client, run_awaiting_approval):
    """Approving a plan transitions to executing."""
    rid = run_awaiting_approval["id"]
    resp = await client.post(f"/api/v1/runs/{rid}/approve-plan", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "executing"


@pytest.mark.asyncio
async def test_reject_plan(client, run_awaiting_approval):
    """Rejecting a plan transitions back to draft with feedback."""
    rid = run_awaiting_approval["id"]
    resp = await client.post(
        f"/api/v1/runs/{rid}/reject-plan",
        json={"feedback": "Split auth into separate tasks"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_approve_wrong_status(client, run):
    """Cannot approve plan when not in awaiting_plan_approval."""
    resp = await client.post(
        f"/api/v1/runs/{run['id']}/approve-plan", json={}
    )
    assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════
# Task Graph
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_set_task_graph_creates_run_tasks(client, run):
    """Setting a task graph creates RunTask rows."""
    rid = run["id"]
    # Transition to planning
    await client.post(
        f"/api/v1/runs/{rid}/status", json={"status": "planning"}
    )
    # Set task graph
    resp = await client.post(
        f"/api/v1/runs/{rid}/task-graph",
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
    tasks_resp = await client.get(f"/api/v1/runs/{rid}/tasks")
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
async def test_budget_ledger_created_with_run(client, run):
    """A budget ledger is created automatically when a run is created."""
    resp = await client.get(f"/api/v1/runs/{run['id']}/budget")
    assert resp.status_code == 200
    budget = resp.json()
    assert budget["budget_limit_usd"] == 5.0
    assert budget["actual_cost_usd"] == 0
    assert budget["status"] == "ok"


@pytest.mark.asyncio
async def test_list_runs_with_status_filter(client, team, run):
    """GET /teams/:id/runs?status=draft filters by status."""
    resp = await client.get(
        f"/api/v1/teams/{team['id']}/runs?status=draft"
    )
    assert resp.status_code == 200
    runs = resp.json()
    assert all(p["status"] == "draft" for p in runs)
