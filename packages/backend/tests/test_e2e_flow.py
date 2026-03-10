"""Full-flow E2E integration test — exercises the complete Entourage lifecycle.

Learn: This test walks through the entire platform lifecycle using the
API alone (no agent subprocess needed). It proves that all the pieces
connect: org → team → agents → task → status transitions → human-in-the-loop
→ review → approve → merge → done.

Run with: uv run pytest tests/test_e2e_flow.py -v

For live agent tests (requires running server + Claude Code CLI):
    uv run pytest tests/test_e2e_flow.py -v --run-e2e
"""

import pytest


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "E2E Org", "slug": "e2e-org"}
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "E2E Team", "slug": "e2e-team"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def agents(client, team):
    """Get auto-created manager + create an engineer."""
    agents_resp = await client.get(f"/api/v1/teams/{team['id']}/agents")
    assert agents_resp.status_code == 200
    manager = agents_resp.json()[0]

    eng_resp = await client.post(
        f"/api/v1/teams/{team['id']}/agents",
        json={"name": "e2e-engineer", "role": "engineer"},
    )
    assert eng_resp.status_code == 201
    engineer = eng_resp.json()
    return manager, engineer


# ═══════════════════════════════════════════════════════════
# Integration test: full lifecycle via API
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_lifecycle_via_api(client, org, team, agents):
    """Complete lifecycle: create → assign → work → human-in-loop → review → approve → done.

    Learn: This exercises every subsystem in a single test:
    1. Task management (CRUD + state machine)
    2. Agent assignment
    3. Human-in-the-loop (ask_human → respond)
    4. Code review (request → approve)
    5. Status transitions through the full lifecycle
    6. Event sourcing (verify audit trail)
    """
    manager, engineer = agents
    team_id = team["id"]

    # ── Step 1: Create task ────────────────────────────────
    task_resp = await client.post(
        f"/api/v1/teams/{team_id}/tasks",
        json={
            "title": "Implement user authentication",
            "description": "Add JWT login endpoint and middleware",
            "priority": "high",
            "tags": ["auth", "security"],
        },
    )
    assert task_resp.status_code == 201
    task = task_resp.json()
    assert task["status"] == "todo"
    assert task["branch"].startswith("task-")
    task_id = task["id"]

    # ── Step 2: Assign to engineer ─────────────────────────
    assign_resp = await client.post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assignee_id": engineer["id"]},
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["assignee_id"] == engineer["id"]

    # ── Step 3: Move to in_progress ────────────────────────
    status_resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress", "actor_id": engineer["id"]},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "in_progress"

    # ── Step 4: Agent asks a human question ────────────────
    hr_resp = await client.post(
        "/api/v1/human-requests",
        json={
            "agent_id": engineer["id"],
            "team_id": team_id,
            "kind": "question",
            "question": "Should I use bcrypt or argon2 for password hashing?",
            "task_id": task_id,
            "options": ["bcrypt", "argon2"],
        },
    )
    assert hr_resp.status_code == 201
    hr = hr_resp.json()
    assert hr["status"] == "pending"
    hr_id = hr["id"]

    # ── Step 5: Human responds ─────────────────────────────
    respond_resp = await client.post(
        f"/api/v1/human-requests/{hr_id}/respond",
        json={"response": "Use argon2 — it's the modern standard"},
    )
    assert respond_resp.status_code == 200
    assert respond_resp.json()["status"] == "resolved"
    assert "argon2" in respond_resp.json()["response"]

    # ── Step 6: Move to in_review ──────────────────────────
    status_resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_review", "actor_id": engineer["id"]},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "in_review"

    # ── Step 7: Request code review ────────────────────────
    review_resp = await client.post(
        f"/api/v1/tasks/{task_id}/reviews",
        json={"reviewer_type": "user"},
    )
    assert review_resp.status_code == 201
    review = review_resp.json()
    assert review["verdict"] is None  # pending

    # ── Step 8: Approve the review ─────────────────────────
    approve_resp = await client.post(
        f"/api/v1/tasks/{task_id}/approve",
        json={
            "verdict": "approve",
            "summary": "Looks great — argon2 is the right choice",
            "reviewer_type": "user",
        },
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["verdict"] == "approve"

    # ── Step 9: Move task through remaining states ─────────
    # Task is still in_review — move to in_approval → merging → done
    await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_approval"},
    )
    await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "merging"},
    )
    done_resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "done"},
    )
    assert done_resp.status_code == 200
    assert done_resp.json()["status"] == "done"
    assert done_resp.json()["completed_at"] is not None

    # ── Step 10: Verify event trail ────────────────────────
    events_resp = await client.get(f"/api/v1/tasks/{task_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()

    event_types = [e["type"] for e in events]
    assert "task.created" in event_types
    assert "task.assigned" in event_types
    assert "task.status_changed" in event_types

    # Count status changes: todo→ip, ip→ir, ir→ia, ia→merging, merging→done = 5
    status_events = [e for e in events if e["type"] == "task.status_changed"]
    assert len(status_events) >= 5


# ═══════════════════════════════════════════════════════════
# Batch task creation with dependencies
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_batch_task_creation_with_dependencies(client, team, agents):
    """Batch endpoint creates tasks with inter-batch depends_on links.

    Learn: This tests the Phase 16 batch endpoint that managers use
    to decompose work. depends_on_indices[0] means "depends on the
    first task in this batch", resolved to real IDs after creation.
    """
    manager, engineer = agents
    team_id = team["id"]

    batch_resp = await client.post(
        f"/api/v1/teams/{team_id}/tasks/batch",
        json={
            "tasks": [
                {
                    "title": "Set up database schema",
                    "description": "Create user and session tables",
                    "priority": "high",
                    "tags": ["database"],
                },
                {
                    "title": "Build API endpoints",
                    "description": "REST endpoints for user CRUD",
                    "priority": "high",
                    "depends_on_indices": [0],
                    "tags": ["api"],
                },
                {
                    "title": "Write integration tests",
                    "description": "Test all endpoints with fixtures",
                    "priority": "medium",
                    "depends_on_indices": [0, 1],
                    "tags": ["testing"],
                },
            ]
        },
    )
    assert batch_resp.status_code == 201
    tasks = batch_resp.json()
    assert len(tasks) == 3

    # Verify all are in 'todo' status
    for t in tasks:
        assert t["status"] == "todo"

    # Verify dependency links
    task_a, task_b, task_c = tasks
    assert task_a["depends_on"] == []
    assert task_b["depends_on"] == [task_a["id"]]
    assert set(task_c["depends_on"]) == {task_a["id"], task_b["id"]}

    # Task A can start (no deps)
    resp = await client.post(
        f"/api/v1/tasks/{task_a['id']}/status",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200

    # Task B CANNOT start (depends on A which is in_progress, not done)
    resp = await client.post(
        f"/api/v1/tasks/{task_b['id']}/status",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 409  # dependency blocked


@pytest.mark.asyncio
async def test_batch_invalid_index(client, team):
    """Batch with out-of-range depends_on_indices returns 422."""
    team_id = team["id"]

    resp = await client.post(
        f"/api/v1/teams/{team_id}/tasks/batch",
        json={
            "tasks": [
                {"title": "Task A"},
                {"title": "Task B", "depends_on_indices": [5]},  # out of range
            ]
        },
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════
# Multi-agent messaging
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_inter_agent_messaging(client, team, agents):
    """Manager sends message to engineer, engineer receives in inbox."""
    manager, engineer = agents
    team_id = team["id"]

    # Manager sends message
    msg_resp = await client.post(
        f"/api/v1/teams/{team_id}/messages",
        json={
            "sender_id": manager["id"],
            "sender_type": "agent",
            "recipient_id": engineer["id"],
            "recipient_type": "agent",
            "content": "Please prioritize the auth task",
        },
    )
    assert msg_resp.status_code == 201

    # Engineer checks inbox
    inbox_resp = await client.get(
        f"/api/v1/agents/{engineer['id']}/inbox",
        params={"unprocessed_only": True},
    )
    assert inbox_resp.status_code == 200
    messages = inbox_resp.json()
    assert len(messages) >= 1
    assert any("prioritize" in m["content"] for m in messages)


# ═══════════════════════════════════════════════════════════
# Cost tracking through a session
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_session_cost_tracking(client, team, agents):
    """Start session → record usage → end session → verify costs."""
    _, engineer = agents
    team_id = team["id"]

    # Create a task for the session
    task_resp = await client.post(
        f"/api/v1/teams/{team_id}/tasks",
        json={"title": "Cost tracking test"},
    )
    task_id = task_resp.json()["id"]

    # Start session via POST /sessions/start
    session_resp = await client.post(
        "/api/v1/sessions/start",
        json={"agent_id": engineer["id"], "task_id": task_id},
    )
    assert session_resp.status_code == 201
    session = session_resp.json()
    session_id = session["id"]

    # Record usage
    usage_resp = await client.post(
        f"/api/v1/sessions/{session_id}/usage",
        json={"tokens_in": 5000, "tokens_out": 2000},
    )
    assert usage_resp.status_code == 200

    # End session
    end_resp = await client.post(f"/api/v1/sessions/{session_id}/end", json={})
    assert end_resp.status_code == 200
    ended = end_resp.json()
    assert ended["ended_at"] is not None
    assert ended["tokens_in"] == 5000
    assert ended["tokens_out"] == 2000

    # Check cost summary
    cost_resp = await client.get(
        f"/api/v1/teams/{team_id}/costs", params={"days": 7}
    )
    assert cost_resp.status_code == 200
    costs = cost_resp.json()
    assert costs["total_cost_usd"] > 0


# ═══════════════════════════════════════════════════════════
# Review with rejection cycle
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_review_rejection_cycle(client, team, agents):
    """Task goes through: in_progress → in_review → rejected → in_progress → in_review → approved.

    Learn: This tests the review loop — tasks can be rejected and sent
    back for more work, then re-submitted for review.
    """
    _, engineer = agents
    team_id = team["id"]

    # Create task
    task_resp = await client.post(
        f"/api/v1/teams/{team_id}/tasks",
        json={"title": "Review cycle test"},
    )
    task_id = task_resp.json()["id"]

    # Move to in_progress → in_review
    await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress", "actor_id": engineer["id"]},
    )
    await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_review", "actor_id": engineer["id"]},
    )

    # Request review
    await client.post(
        f"/api/v1/tasks/{task_id}/reviews",
        json={"reviewer_type": "user"},
    )

    # Reject
    reject_resp = await client.post(
        f"/api/v1/tasks/{task_id}/reject",
        json={"verdict": "reject", "summary": "Missing error handling", "reviewer_type": "user"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["verdict"] == "reject"

    # Move task back to in_progress manually (reject doesn't auto-transition)
    back_resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress"},
    )
    assert back_resp.status_code == 200

    # Re-submit for review
    await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_review", "actor_id": engineer["id"]},
    )

    # Request new review
    await client.post(
        f"/api/v1/tasks/{task_id}/reviews",
        json={"reviewer_type": "user"},
    )

    # Approve this time
    approve_resp = await client.post(
        f"/api/v1/tasks/{task_id}/approve",
        json={"verdict": "approve", "summary": "Error handling added — approved", "reviewer_type": "user"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["verdict"] == "approve"


# ═══════════════════════════════════════════════════════════
# Live agent test (requires --run-e2e)
# ═══════════════════════════════════════════════════════════


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_live_agent_run(client, team, agents):
    """Live test: dispatches a real agent via Claude Code.

    Only runs with --run-e2e flag. Requires:
    - Running Entourage server (uvicorn openclaw.main:app)
    - Claude Code CLI installed (claude binary on PATH)
    - Valid ANTHROPIC_API_KEY

    Creates a simple task, dispatches the agent, polls until done.
    """
    _, engineer = agents
    team_id = team["id"]

    # Create a trivial task
    task_resp = await client.post(
        f"/api/v1/teams/{team_id}/tasks",
        json={
            "title": "Create hello.py",
            "description": "Create a file hello.py that prints 'Hello from Entourage!'",
            "priority": "low",
        },
    )
    task_id = task_resp.json()["id"]

    # Assign to engineer
    await client.post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assignee_id": engineer["id"]},
    )

    # Dispatch agent run
    run_resp = await client.post(
        f"/api/v1/agents/{engineer['id']}/run",
        json={"task_id": task_id},
    )
    assert run_resp.status_code in (200, 202)

    # Poll for completion (max 5 minutes)
    import asyncio

    status = "todo"
    for _ in range(60):  # 60 * 5s = 300s = 5 min
        await asyncio.sleep(5)
        task_resp = await client.get(f"/api/v1/tasks/{task_id}")
        status = task_resp.json()["status"]
        if status in ("in_review", "done", "cancelled"):
            break
    else:
        pytest.fail(f"Task {task_id} did not complete within 5 minutes (status={status})")

    # Verify task progressed past in_progress
    assert status in ("in_review", "done"), f"Expected in_review/done, got {status}"

    # Verify session was recorded
    cost_resp = await client.get(
        f"/api/v1/teams/{team_id}/costs", params={"days": 1}
    )
    assert cost_resp.json()["total_sessions"] >= 1
