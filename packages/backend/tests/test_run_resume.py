"""Tests for run resume logic in ExecutionLoop.resume()."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.execution_loop import ExecutionLoop


def _make_mock_session_factory(mock_db):
    """Wrap a mock DB in an async context manager factory."""
    @asynccontextmanager
    async def factory():
        yield mock_db
    return factory


def _make_task(id, status, agent_id=None):
    task = MagicMock()
    task.id = id
    task.status = status
    task.agent_id = agent_id
    task.started_at = "2024-01-01T00:00:00Z" if status == "in_progress" else None
    return task


def _make_run(status="paused"):
    run = MagicMock()
    run.id = "run-1"
    run.status = status
    run.team_id = "team-1"
    return run


class TestResumeLogic:
    """Test the resume state reconstruction logic.

    Note: These test the state reset behavior — they don't run the full
    execution loop (that requires integration testing with a real DB).
    """

    @pytest.mark.asyncio
    async def test_resets_in_progress_to_todo(self):
        """Resume resets interrupted in_progress tasks back to todo."""
        mock_run = _make_run("paused")
        tasks = [
            _make_task(1, "done"),
            _make_task(2, "in_progress", agent_id="agent-1"),
            _make_task(3, "todo"),
        ]

        # Setup mock result for scalars().all()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = tasks
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_run)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.change_status = AsyncMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.RunService", return_value=mock_svc):
            with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
                # Mock run() to avoid the actual execution loop
                with patch.object(loop, "run", new_callable=AsyncMock, return_value={"status": "reviewing"}):
                    result = await loop.resume("run-1")

        # The in_progress task should be reset
        assert tasks[1].status == "todo"
        assert tasks[1].agent_id is None
        assert tasks[1].started_at is None

        # Done task should be preserved
        assert tasks[0].status == "done"

        # Todo task should remain todo
        assert tasks[2].status == "todo"

    @pytest.mark.asyncio
    async def test_preserves_completed_tasks(self):
        """Resume doesn't touch tasks that are already done."""
        mock_run = _make_run("paused")
        tasks = [
            _make_task(1, "done"),
            _make_task(2, "done"),
            _make_task(3, "in_progress"),
        ]

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = tasks
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_run)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.change_status = AsyncMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.RunService", return_value=mock_svc):
            with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
                with patch.object(loop, "run", new_callable=AsyncMock, return_value={"status": "reviewing"}):
                    await loop.resume("run-1")

        # Done tasks preserved
        assert tasks[0].status == "done"
        assert tasks[1].status == "done"

        # In-progress reset
        assert tasks[2].status == "todo"

    @pytest.mark.asyncio
    async def test_resume_records_event(self):
        """Resume records a RUN_RESUMED event."""
        mock_run = _make_run("paused")
        tasks = [_make_task(1, "in_progress")]

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = tasks
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_run)
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.change_status = AsyncMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.RunService", return_value=mock_svc):
            with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
                with patch.object(loop, "run", new_callable=AsyncMock, return_value={"status": "reviewing"}):
                    await loop.resume("run-1")

        # Check that RUN_RESUMED event was recorded
        mock_events.append.assert_called_once()
        call_kwargs = mock_events.append.call_args
        assert call_kwargs.kwargs["event_type"] == "run.resumed"
        assert call_kwargs.kwargs["data"]["reset_tasks"] == 1

    @pytest.mark.asyncio
    async def test_resume_invalid_status_raises(self):
        """Resume raises ValueError for runs not in resumable status."""
        mock_run = _make_run("draft")

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_run)

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with pytest.raises(ValueError, match="Cannot resume"):
            await loop.resume("run-1")
