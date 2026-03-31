"""Tests for SiblingContextBuilder — parallel task awareness injection."""

import pytest

from openclaw.services.sibling_context import SiblingContextBuilder


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Sib Org", "slug": "sib-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Sib Team", "slug": "sib-team"},
    )
    return resp.json()


@pytest.fixture
async def executing_run(client, team):
    """Create a run in executing state with 3 tasks: A (no deps), B (no deps), C (depends on 0)."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/runs",
        json={
            "title": "Parallel Build",
            "intent": "Build feature with parallel tasks",
        },
    )
    run = resp.json()
    rid = run["id"]

    # planning
    await client.post(f"/api/v1/runs/{rid}/status", json={"status": "planning"})

    # Set task graph
    await client.post(
        f"/api/v1/runs/{rid}/task-graph",
        json={
            "task_graph": {
                "tasks": [
                    {"title": "Task A: Database schema", "description": "Create tables", "complexity": "M", "assigned_role": "engineer", "dependencies": []},
                    {"title": "Task B: API routes", "description": "Build REST endpoints", "complexity": "M", "assigned_role": "engineer", "dependencies": []},
                    {"title": "Task C: Integration tests", "description": "Test everything", "complexity": "M", "assigned_role": "engineer", "dependencies": [0]},
                ]
            }
        },
    )

    # awaiting_plan_approval → executing
    await client.post(f"/api/v1/runs/{rid}/status", json={"status": "awaiting_plan_approval"})
    await client.post(f"/api/v1/runs/{rid}/approve-plan", json={})

    # Get tasks
    tasks_resp = await client.get(f"/api/v1/runs/{rid}/tasks")
    tasks = tasks_resp.json()

    resp = await client.get(f"/api/v1/runs/{rid}")
    run_data = resp.json()
    run_data["run_tasks"] = tasks

    return run_data


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestSiblingContextBuilder:
    """Test sibling context generation."""

    async def test_single_task_returns_empty(self, client, team, db_session):
        """A run with only one task has no siblings."""
        resp = await client.post(
            f"/api/v1/teams/{team['id']}/runs",
            json={"title": "Solo Run", "intent": "One task only"},
        )
        run = resp.json()
        rid = run["id"]

        await client.post(f"/api/v1/runs/{rid}/status", json={"status": "planning"})
        await client.post(
            f"/api/v1/runs/{rid}/task-graph",
            json={
                "task_graph": {
                    "tasks": [
                        {"title": "Only task", "description": "Solo", "complexity": "S", "assigned_role": "engineer", "dependencies": []},
                    ]
                }
            },
        )
        await client.post(f"/api/v1/runs/{rid}/status", json={"status": "awaiting_plan_approval"})
        await client.post(f"/api/v1/runs/{rid}/approve-plan", json={})

        tasks_resp = await client.get(f"/api/v1/runs/{rid}/tasks")
        tasks = tasks_resp.json()

        builder = SiblingContextBuilder(db_session)
        task_id = tasks[0]["id"]
        context = await builder.build_context(rid, task_id)
        assert context == ""

    async def test_parallel_siblings_detected(self, db_session, executing_run):
        """Tasks A and B (no deps on each other) should appear as parallel siblings."""
        run = executing_run
        tasks = run["run_tasks"]

        task_a = next(t for t in tasks if "Task A" in t["title"])

        builder = SiblingContextBuilder(db_session)
        context = await builder.build_context(run["id"], task_a["id"])

        assert "PARALLEL TASKS" in context
        assert "Task B" in context

    async def test_successor_detected(self, db_session, executing_run):
        """Task C depends on Task A, so C should appear as 'waiting on you' for A."""
        run = executing_run
        tasks = run["run_tasks"]

        task_a = next(t for t in tasks if "Task A" in t["title"])

        builder = SiblingContextBuilder(db_session)
        context = await builder.build_context(run["id"], task_a["id"])

        assert "TASKS WAITING ON YOU" in context
        assert "Task C" in context

    async def test_nonexistent_task_returns_empty(self, db_session, executing_run):
        """Asking for context of a task ID that doesn't exist returns empty."""
        builder = SiblingContextBuilder(db_session)
        context = await builder.build_context(executing_run["id"], 999999)
        assert context == ""
