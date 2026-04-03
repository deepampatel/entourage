"""Phase 2 API tests — Tasks, state machine, dependencies, messages.

Learn: These tests verify the DAG-enforced state machine, which is
the most important business logic in the system. We test:
1. Task CRUD
2. Valid and invalid status transitions
3. Dependency enforcement (can't start blocked tasks)
4. Event sourcing (every change recorded)
5. Messages (inter-agent communication)

Pattern: Build up test data using the API (org → team → agents → tasks).
"""

import pytest


# ═══════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post("/api/v1/orgs", json={"name": "Task Org", "slug": "task-org"})
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Task Team", "slug": "task-team"},
    )
    return resp.json()


@pytest.fixture
async def agents(client, team):
    """Create two agents and return them as (manager, engineer)."""
    # The team auto-creates a manager, so list to find it
    agents_resp = await client.get(f"/api/v1/teams/{team['id']}/agents")
    manager = agents_resp.json()[0]

    # Create an engineer
    eng_resp = await client.post(
        f"/api/v1/teams/{team['id']}/agents",
        json={"name": "eng-1", "role": "engineer"},
    )
    engineer = eng_resp.json()
    return manager, engineer


# ═══════════════════════════════════════════════════════════
# Task CRUD
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_task(client, team):
    """POST /teams/:id/tasks should create a task in 'todo' status."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Fix login bug", "priority": "high", "tags": ["bug", "auth"]},
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["title"] == "Fix login bug"
    assert task["status"] == "todo"
    assert task["priority"] == "high"
    assert task["tags"] == ["bug", "auth"]
    assert task["branch"].startswith("task-")
    assert "fix-login-bug" in task["branch"]


@pytest.mark.asyncio
async def test_create_task_with_assignment(client, team, agents):
    """Task can be created with an assignee."""
    _, engineer = agents
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Build API", "assignee_id": engineer["id"]},
    )
    assert resp.status_code == 201
    assert resp.json()["assignee_id"] == engineer["id"]


@pytest.mark.asyncio
async def test_list_tasks(client, team):
    """GET /teams/:id/tasks should list all tasks."""
    await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A"},
    )
    await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B"},
    )

    resp = await client.get(f"/api/v1/teams/{team['id']}/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status(client, team):
    """Tasks can be filtered by status."""
    # Create two tasks, move one to in_progress
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Still todo"},
    )
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Started"},
    )
    task_b = resp_b.json()
    await client.post(
        f"/api/v1/tasks/{task_b['id']}/status",
        json={"status": "in_progress"},
    )

    # Filter by in_progress
    resp = await client.get(
        f"/api/v1/teams/{team['id']}/tasks",
        params={"status": "in_progress"},
    )
    tasks = resp.json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Started"


@pytest.mark.asyncio
async def test_list_tasks_excludes_archived_by_default(client, team):
    """Archived tasks are hidden from list endpoint unless explicitly included."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Archive me"},
    )
    task_id = resp.json()["id"]

    for status in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        await client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": status},
        )

    archive_resp = await client.post(f"/api/v1/tasks/{task_id}/archive", json={})
    assert archive_resp.status_code == 200
    assert archive_resp.json()["status"] == "archived"

    list_resp = await client.get(f"/api/v1/teams/{team['id']}/tasks")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_list_tasks_include_archived_flag(client, team):
    """include_archived=true returns archived tasks in the default listing."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Archive me too"},
    )
    task_id = resp.json()["id"]

    for status in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        await client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": status},
        )

    await client.post(f"/api/v1/tasks/{task_id}/archive", json={})

    list_resp = await client.get(
        f"/api/v1/teams/{team['id']}/tasks",
        params={"include_archived": "true"},
    )
    assert list_resp.status_code == 200
    tasks = list_resp.json()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "archived"


@pytest.mark.asyncio
async def test_get_task(client, team):
    """GET /tasks/:id should return task details."""
    create_resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Get me"},
    )
    task_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get me"


@pytest.mark.asyncio
async def test_get_task_404(client):
    """GET /tasks/:id for non-existent task returns 404."""
    resp = await client.get("/api/v1/tasks/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_task(client, team):
    """PATCH /tasks/:id should partially update task fields."""
    create_resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Original"},
    )
    task_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"title": "Updated", "priority": "critical"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"
    assert resp.json()["priority"] == "critical"


@pytest.mark.asyncio
async def test_assign_task(client, team, agents):
    """POST /tasks/:id/assign should set the assignee."""
    _, engineer = agents
    create_resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Assign me"},
    )
    task_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/tasks/{task_id}/assign",
        json={"assignee_id": engineer["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["assignee_id"] == engineer["id"]


# ═══════════════════════════════════════════════════════════
# State Machine — valid transitions
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_status_todo_to_in_progress(client, team):
    """todo → in_progress is a valid transition."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Start me"},
    )
    task_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_full_workflow(client, team):
    """Task can go through the complete workflow: todo → done."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Full workflow"},
    )
    task_id = resp.json()["id"]

    # todo → in_progress → in_review → in_approval → merging → done
    for status in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        resp = await client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": status},
        )
        assert resp.status_code == 200, f"Failed at transition to {status}: {resp.json()}"
        assert resp.json()["status"] == status

    # Verify completed_at is set
    assert resp.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_cancel_from_any_active_state(client, team):
    """Tasks can be cancelled from any non-terminal state."""
    for start_status in ["todo", "in_progress", "in_review", "in_approval"]:
        resp = await client.post(
            f"/api/v1/teams/{team['id']}/tasks",
            json={"title": f"Cancel from {start_status}"},
        )
        task_id = resp.json()["id"]

        # Move to start_status
        if start_status != "todo":
            transitions = {
                "in_progress": ["in_progress"],
                "in_review": ["in_progress", "in_review"],
                "in_approval": ["in_progress", "in_review", "in_approval"],
            }
            for s in transitions[start_status]:
                await client.post(
                    f"/api/v1/tasks/{task_id}/status",
                    json={"status": s},
                )

        # Cancel
        resp = await client.post(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "cancelled"},
        )
        assert resp.status_code == 200, f"Failed to cancel from {start_status}"
        assert resp.json()["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════
# State Machine — INVALID transitions
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_invalid_transition_skip_steps(client, team):
    """Can't skip from 'todo' directly to 'in_review' (must go through in_progress)."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Skip steps"},
    )
    task_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_review"},
    )
    assert resp.status_code == 409  # Conflict


@pytest.mark.asyncio
async def test_invalid_transition_from_done(client, team):
    """Can't transition from 'done' to active states."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Terminal state"},
    )
    task_id = resp.json()["id"]

    # Move through to done
    for s in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        await client.post(f"/api/v1/tasks/{task_id}/status", json={"status": s})

    # Try to go back
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_invalid_transition_from_cancelled(client, team):
    """Can't transition from 'cancelled' to active states."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Cancelled task"},
    )
    task_id = resp.json()["id"]

    await client.post(f"/api/v1/tasks/{task_id}/status", json={"status": "cancelled"})

    resp = await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "todo"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_archive_done_task(client, team):
    """Done tasks can be archived."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Archive done"},
    )
    task_id = resp.json()["id"]

    for s in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        await client.post(f"/api/v1/tasks/{task_id}/status", json={"status": s})

    archive_resp = await client.post(f"/api/v1/tasks/{task_id}/archive", json={})
    assert archive_resp.status_code == 200
    assert archive_resp.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_archive_cancelled_task(client, team):
    """Cancelled tasks can be archived."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Archive cancelled"},
    )
    task_id = resp.json()["id"]

    await client.post(
        f"/api/v1/tasks/{task_id}/status",
        json={"status": "cancelled"},
    )
    archive_resp = await client.post(f"/api/v1/tasks/{task_id}/archive", json={})
    assert archive_resp.status_code == 200
    assert archive_resp.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_archive_rejected_for_active_task(client, team):
    """Only done/cancelled tasks can be archived."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Not ready"},
    )
    task_id = resp.json()["id"]

    archive_resp = await client.post(f"/api/v1/tasks/{task_id}/archive", json={})
    assert archive_resp.status_code == 409
    assert "can be archived" in archive_resp.json()["detail"]


# ═══════════════════════════════════════════════════════════
# DAG Dependency Enforcement
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dependency_blocks_start(client, team):
    """Can't start a task if its dependencies aren't done.

    Learn: This is the DAG enforcement — task B depends on task A,
    so B can't move to in_progress until A is done.
    """
    # Create task A (no deps)
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A (dependency)"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B (depends on A)
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B (blocked)", "depends_on": [task_a_id]},
    )
    task_b_id = resp_b.json()["id"]

    # Try to start B — should fail (A is still 'todo')
    resp = await client.post(
        f"/api/v1/tasks/{task_b_id}/status",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 409
    assert "dependencies" in resp.json()["detail"].lower() or "blocked" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dependency_unblocks_after_done(client, team):
    """Once dependency is done, the blocked task can start."""
    # Create task A
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B (depends on A)
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B", "depends_on": [task_a_id]},
    )
    task_b_id = resp_b.json()["id"]

    # Complete A
    for s in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        await client.post(f"/api/v1/tasks/{task_a_id}/status", json={"status": s})

    # Now B should be able to start
    resp = await client.post(
        f"/api/v1/tasks/{task_b_id}/status",
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_get_task_with_dependent_tasks_info(client, team):
    """GET /tasks/:id should return dependent task information.

    Learn: The API enriches task responses with dependent_tasks array,
    containing id, title, and status for each task in the depends_on list.
    This allows the frontend to show dependency status without extra API calls.
    """
    # Create task A
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A - Foundation", "priority": "high"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B - API Layer", "priority": "medium"},
    )
    task_b_id = resp_b.json()["id"]

    # Create task C (depends on A and B)
    resp_c = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task C - Integration", "depends_on": [task_a_id, task_b_id]},
    )
    task_c = resp_c.json()
    task_c_id = task_c["id"]

    # Verify depends_on is set correctly
    assert task_c["depends_on"] == [task_a_id, task_b_id]

    # Get task C with details
    resp = await client.get(f"/api/v1/tasks/{task_c_id}")
    assert resp.status_code == 200
    task_detail = resp.json()

    # Verify dependent_tasks array exists and has correct structure
    assert "dependent_tasks" in task_detail
    assert len(task_detail["dependent_tasks"]) == 2

    # Verify each dependent task has id, title, and status
    dep_tasks = {dt["id"]: dt for dt in task_detail["dependent_tasks"]}

    assert task_a_id in dep_tasks
    assert dep_tasks[task_a_id]["title"] == "Task A - Foundation"
    assert dep_tasks[task_a_id]["status"] == "todo"

    assert task_b_id in dep_tasks
    assert dep_tasks[task_b_id]["title"] == "Task B - API Layer"
    assert dep_tasks[task_b_id]["status"] == "todo"

    # Update task A status and verify it's reflected
    await client.post(
        f"/api/v1/tasks/{task_a_id}/status",
        json={"status": "in_progress"}
    )

    # Get task C again
    resp = await client.get(f"/api/v1/tasks/{task_c_id}")
    task_detail = resp.json()
    dep_tasks = {dt["id"]: dt for dt in task_detail["dependent_tasks"]}

    # Verify task A status is updated
    assert dep_tasks[task_a_id]["status"] == "in_progress"
    assert dep_tasks[task_b_id]["status"] == "todo"


@pytest.mark.asyncio
async def test_list_tasks_with_dependent_tasks_info(client, team):
    """GET /teams/:id/tasks should include dependent task information.

    Learn: The list endpoint also enriches each task with dependent_tasks,
    allowing the UI to show dependency status in list views without N+1 queries.
    """
    # Create task A
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B (depends on A)
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B", "depends_on": [task_a_id]},
    )

    # List tasks
    resp = await client.get(f"/api/v1/teams/{team['id']}/tasks")
    assert resp.status_code == 200
    tasks = resp.json()

    # Find task B in the list
    task_b = next(t for t in tasks if t["title"] == "Task B")

    # Verify dependent_tasks is included
    assert "dependent_tasks" in task_b
    assert len(task_b["dependent_tasks"]) == 1
    assert task_b["dependent_tasks"][0]["id"] == task_a_id
    assert task_b["dependent_tasks"][0]["title"] == "Task A"
    assert task_b["dependent_tasks"][0]["status"] == "todo"


@pytest.mark.asyncio
async def test_dependent_tasks_empty_for_no_dependencies(client, team):
    """Tasks without dependencies should have empty dependent_tasks array."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Independent Task"},
    )
    task_id = resp.json()["id"]

    # Get task detail
    resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    task = resp.json()

    # Verify dependent_tasks is empty array
    assert "dependent_tasks" in task
    assert task["dependent_tasks"] == []
    assert task["depends_on"] == []


@pytest.mark.asyncio
async def test_dependent_tasks_status_changes_reflected(client, team):
    """Dependent task status changes should be reflected in subsequent queries.

    Learn: This tests the real-time accuracy of the dependent_tasks data,
    ensuring the UI always sees current status information.
    """
    # Create task A
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A - Dependency"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B (depends on A)
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B - Dependent", "depends_on": [task_a_id]},
    )
    task_b_id = resp_b.json()["id"]

    # Verify initial status
    resp = await client.get(f"/api/v1/tasks/{task_b_id}")
    task_b = resp.json()
    assert task_b["dependent_tasks"][0]["status"] == "todo"

    # Move task A through several status changes
    status_sequence = ["in_progress", "in_review", "in_approval", "merging", "done"]
    for status in status_sequence:
        await client.post(
            f"/api/v1/tasks/{task_a_id}/status",
            json={"status": status}
        )

        # Verify status is reflected in task B's dependent_tasks
        resp = await client.get(f"/api/v1/tasks/{task_b_id}")
        task_b = resp.json()
        assert task_b["dependent_tasks"][0]["status"] == status, \
            f"Expected status {status} but got {task_b['dependent_tasks'][0]['status']}"


@pytest.mark.asyncio
async def test_dependent_tasks_multiple_dependencies_all_statuses(client, team):
    """Task with multiple dependencies should show all dependency statuses.

    Learn: UI needs to see all dependencies at once to determine if a task
    is blocked or ready to start. This tests the N-dependency case.
    """
    # Create three dependency tasks
    task_ids = []
    for i in range(3):
        resp = await client.post(
            f"/api/v1/teams/{team['id']}/tasks",
            json={"title": f"Dependency {i+1}", "priority": ["low", "medium", "high"][i]},
        )
        task_ids.append(resp.json()["id"])

    # Create task that depends on all three
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Main Task", "depends_on": task_ids},
    )
    main_task_id = resp.json()["id"]

    # Move each dependency to different status
    await client.post(f"/api/v1/tasks/{task_ids[0]}/status", json={"status": "in_progress"})
    await client.post(f"/api/v1/tasks/{task_ids[1]}/status", json={"status": "in_progress"})
    await client.post(f"/api/v1/tasks/{task_ids[1]}/status", json={"status": "in_review"})
    # task_ids[2] stays in 'todo'

    # Get main task and verify all dependency statuses
    resp = await client.get(f"/api/v1/tasks/{main_task_id}")
    main_task = resp.json()

    assert len(main_task["dependent_tasks"]) == 3
    dep_tasks_by_id = {dt["id"]: dt for dt in main_task["dependent_tasks"]}

    assert dep_tasks_by_id[task_ids[0]]["status"] == "in_progress"
    assert dep_tasks_by_id[task_ids[0]]["title"] == "Dependency 1"

    assert dep_tasks_by_id[task_ids[1]]["status"] == "in_review"
    assert dep_tasks_by_id[task_ids[1]]["title"] == "Dependency 2"

    assert dep_tasks_by_id[task_ids[2]]["status"] == "todo"
    assert dep_tasks_by_id[task_ids[2]]["title"] == "Dependency 3"


@pytest.mark.asyncio
async def test_dependent_tasks_ordering_preserved(client, team):
    """Dependent tasks should maintain the same order as depends_on array.

    Learn: UI may rely on the order of dependencies for display purposes.
    The API should preserve the order from the depends_on array.
    """
    # Create three tasks
    task_ids = []
    for i in range(3):
        resp = await client.post(
            f"/api/v1/teams/{team['id']}/tasks",
            json={"title": f"Task {chr(65+i)}"},  # A, B, C
        )
        task_ids.append(resp.json()["id"])

    # Create dependent task with specific order
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Dependent", "depends_on": task_ids},
    )
    dependent_id = resp.json()["id"]

    # Get task and verify order matches
    resp = await client.get(f"/api/v1/tasks/{dependent_id}")
    task = resp.json()

    # Extract IDs from dependent_tasks in order
    dependent_ids_in_order = [dt["id"] for dt in task["dependent_tasks"]]

    # Should match the original depends_on order
    assert dependent_ids_in_order == task_ids


@pytest.mark.asyncio
async def test_dependent_tasks_cancelled_dependency_shows_status(client, team):
    """Cancelled dependencies should be reflected in dependent_tasks.

    Learn: UI needs to know if a dependency was cancelled so it can
    show the task as potentially unblocked (depending on requirements).
    """
    # Create task A
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B (depends on A)
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B", "depends_on": [task_a_id]},
    )
    task_b_id = resp_b.json()["id"]

    # Cancel task A
    await client.post(
        f"/api/v1/tasks/{task_a_id}/status",
        json={"status": "cancelled"}
    )

    # Get task B and verify dependency status
    resp = await client.get(f"/api/v1/tasks/{task_b_id}")
    task_b = resp.json()

    assert len(task_b["dependent_tasks"]) == 1
    assert task_b["dependent_tasks"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_tasks_filtered_by_status_includes_dependent_tasks(client, team):
    """Filtered task list should still include dependent_tasks information.

    Learn: When filtering tasks by status, we still need dependency info
    for UI display. This ensures the enrichment works with filters.
    """
    # Create task A
    resp_a = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task A"},
    )
    task_a_id = resp_a.json()["id"]

    # Create task B (depends on A)
    resp_b = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Task B", "depends_on": [task_a_id]},
    )
    task_b_id = resp_b.json()["id"]

    # Move task B to in_progress (this should fail due to dependency)
    # But first complete task A so B can start
    for status in ["in_progress", "in_review", "in_approval", "merging", "done"]:
        await client.post(f"/api/v1/tasks/{task_a_id}/status", json={"status": status})

    # Now start task B
    await client.post(f"/api/v1/tasks/{task_b_id}/status", json={"status": "in_progress"})

    # Filter by in_progress status
    resp = await client.get(
        f"/api/v1/teams/{team['id']}/tasks",
        params={"status": "in_progress"}
    )
    assert resp.status_code == 200
    tasks = resp.json()

    # Should have task B
    assert len(tasks) == 1
    task_b = tasks[0]

    # Verify dependent_tasks is included even with filter
    assert "dependent_tasks" in task_b
    assert len(task_b["dependent_tasks"]) == 1
    assert task_b["dependent_tasks"][0]["id"] == task_a_id
    assert task_b["dependent_tasks"][0]["status"] == "done"


# ═══════════════════════════════════════════════════════════
# Event Sourcing
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_task_events_trail(client, team):
    """Every task change should create events in the event log."""
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Event trail"},
    )
    task_id = resp.json()["id"]

    # Move through states
    await client.post(f"/api/v1/tasks/{task_id}/status", json={"status": "in_progress"})
    await client.patch(f"/api/v1/tasks/{task_id}", json={"priority": "high"})

    # Get events
    resp = await client.get(f"/api/v1/tasks/{task_id}/events")
    assert resp.status_code == 200
    events = resp.json()

    types = [e["type"] for e in events]
    assert "task.created" in types
    assert "task.status_changed" in types
    assert "task.updated" in types

    # Verify status change event has from/to
    status_event = next(e for e in events if e["type"] == "task.status_changed")
    assert status_event["data"]["from"] == "todo"
    assert status_event["data"]["to"] == "in_progress"


# ═══════════════════════════════════════════════════════════
# Messages
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_message(client, team, agents):
    """POST /teams/:id/messages should send a message."""
    manager, engineer = agents

    resp = await client.post(
        f"/api/v1/teams/{team['id']}/messages",
        json={
            "sender_id": manager["id"],
            "sender_type": "agent",
            "recipient_id": engineer["id"],
            "recipient_type": "agent",
            "content": "Please work on the login bug.",
        },
    )
    assert resp.status_code == 201
    msg = resp.json()
    assert msg["content"] == "Please work on the login bug."
    assert msg["sender_id"] == manager["id"]
    assert msg["recipient_id"] == engineer["id"]


@pytest.mark.asyncio
async def test_get_inbox(client, team, agents):
    """GET /agents/:id/inbox should return unprocessed messages."""
    manager, engineer = agents

    # Send two messages to the engineer
    await client.post(
        f"/api/v1/teams/{team['id']}/messages",
        json={
            "sender_id": manager["id"],
            "sender_type": "agent",
            "recipient_id": engineer["id"],
            "recipient_type": "agent",
            "content": "Message 1",
        },
    )
    await client.post(
        f"/api/v1/teams/{team['id']}/messages",
        json={
            "sender_id": manager["id"],
            "sender_type": "agent",
            "recipient_id": engineer["id"],
            "recipient_type": "agent",
            "content": "Message 2",
        },
    )

    # Check inbox
    resp = await client.get(f"/api/v1/agents/{engineer['id']}/inbox")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    contents = [m["content"] for m in messages]
    assert "Message 1" in contents
    assert "Message 2" in contents
