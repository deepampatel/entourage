"""Tests for parallel execution logic in ExecutionLoop.

These test the _find_ready_tasks() and _find_idle_agents() methods that
drive parallel dispatch. The actual run() loop requires integration testing
with a real DB + agent runner.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.execution_loop import ExecutionLoop


def _make_task(
    id: int,
    status: str = "todo",
    dependencies: list[int] | None = None,
    assigned_role: str = "engineer",
) -> MagicMock:
    """Create a mock RunTask."""
    task = MagicMock()
    task.id = id
    task.status = status
    task.dependencies = dependencies or []
    task.assigned_role = assigned_role
    task.title = f"Task {id}"
    task.description = f"Description for task {id}"
    task.agent_id = None
    task.started_at = None
    task.completed_at = None
    task.error = None
    return task


class TestFindReadyTasks:
    """Test the _find_ready_tasks() parallel discovery."""

    def test_returns_single_ready_task(self):
        """With max_count=1, returns at most 1 task (serial behavior)."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="todo"),
            _make_task(1, status="todo"),
        ]

        ready = loop._find_ready_tasks(tasks, max_count=1)

        assert len(ready) == 1
        assert ready[0].id == 0

    def test_returns_multiple_ready_tasks(self):
        """When multiple tasks have no dependencies, returns them all."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="todo"),
            _make_task(1, status="todo"),
            _make_task(2, status="todo"),
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 3

    def test_respects_max_count(self):
        """Never returns more tasks than max_count."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="todo"),
            _make_task(1, status="todo"),
            _make_task(2, status="todo"),
            _make_task(3, status="todo"),
        ]

        ready = loop._find_ready_tasks(tasks, max_count=2)

        assert len(ready) == 2

    def test_respects_dependencies(self):
        """Tasks with unmet dependencies are not returned."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="done"),             # Task 0: done
            _make_task(1, status="todo", dependencies=[0]),  # Task 1: deps met
            _make_task(2, status="todo", dependencies=[1]),  # Task 2: deps NOT met (1 not done)
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 1
        assert ready[0].id == 1

    def test_parallel_tasks_with_shared_dependency(self):
        """Multiple tasks depending on the same done task are all ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="done"),             # Task 0: done
            _make_task(1, status="todo", dependencies=[0]),  # Ready
            _make_task(2, status="todo", dependencies=[0]),  # Ready
            _make_task(3, status="todo", dependencies=[0]),  # Ready
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 3
        assert {r.id for r in ready} == {1, 2, 3}

    def test_skips_in_progress_tasks(self):
        """Tasks already in_progress are not returned as ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="in_progress"),
            _make_task(1, status="todo"),
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 1
        assert ready[0].id == 1

    def test_no_ready_tasks(self):
        """Returns empty list when no tasks are ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="in_progress"),
            _make_task(1, status="todo", dependencies=[0]),
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 0

    def test_diamond_dependency(self):
        """Diamond pattern: A→B, A→C, B+C→D. After A done, B and C are ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="done"),                   # A
            _make_task(1, status="todo", dependencies=[0]),  # B (ready)
            _make_task(2, status="todo", dependencies=[0]),  # C (ready)
            _make_task(3, status="todo", dependencies=[1, 2]),  # D (not ready)
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 2
        assert {r.id for r in ready} == {1, 2}

    def test_all_done_returns_empty(self):
        """When all tasks are done, no tasks are ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="done"),
            _make_task(1, status="done"),
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 0

    def test_invalid_dependency_index(self):
        """Tasks with out-of-range dependency indices are not ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="todo", dependencies=[99]),  # Invalid dep
        ]

        ready = loop._find_ready_tasks(tasks, max_count=4)

        assert len(ready) == 0


class TestFindReadyTaskBackwardCompat:
    """Test the _find_ready_task() singular alias."""

    def test_returns_single_task(self):
        """The singular method returns one task or None."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="todo"),
            _make_task(1, status="todo"),
        ]

        task = loop._find_ready_task(tasks)

        assert task is not None
        assert task.id == 0

    def test_returns_none_when_no_ready(self):
        """Returns None when no tasks are ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="in_progress"),
        ]

        task = loop._find_ready_task(tasks)

        assert task is None


class TestSerialMode:
    """Test that max_concurrent_run_tasks=1 preserves serial behavior."""

    def test_serial_mode_finds_one_task(self):
        """When max_count=1, only one task is returned even if many are ready."""
        loop = ExecutionLoop()
        tasks = [
            _make_task(0, status="todo"),
            _make_task(1, status="todo"),
            _make_task(2, status="todo"),
        ]

        # Simulate serial mode: slots = 1 - 0 running = 1
        ready = loop._find_ready_tasks(tasks, max_count=1)

        assert len(ready) == 1


class TestCancelRunning:
    """Test the _cancel_running cleanup method."""

    @pytest.mark.asyncio
    async def test_cancel_running_cancels_futures(self):
        """All running futures are cancelled."""
        loop = ExecutionLoop()

        fut1 = MagicMock()
        fut1.done.return_value = False
        fut1.cancel.return_value = True

        fut2 = MagicMock()
        fut2.done.return_value = True  # Already done

        running = {1: fut1, 2: fut2}

        with patch("asyncio.gather", new_callable=AsyncMock):
            await loop._cancel_running(running)

        fut1.cancel.assert_called_once()
        fut2.cancel.assert_not_called()  # Already done
        assert len(running) == 0
