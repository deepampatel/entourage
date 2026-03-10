"""Tests for task retry logic in ExecutionLoop._handle_task_completion."""

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


def _make_ptask(
    id: int = 1,
    status: str = "in_progress",
    retry_count: int = 0,
    title: str = "Test Task",
):
    """Create a mock PipelineTask for retry testing."""
    task = MagicMock()
    task.id = id
    task.status = status
    task.retry_count = retry_count
    task.title = title
    task.agent_id = "agent-1"
    task.started_at = None
    task.completed_at = None
    task.error = None
    return task


class TestHandleTaskCompletion:
    @pytest.mark.asyncio
    async def test_success_marks_done(self):
        """Successful task is marked as done."""
        mock_task = _make_ptask()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_task)
        mock_db.commit = AsyncMock()
        mock_db.add = MagicMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
            with patch.object(loop, "_publish_event", new_callable=AsyncMock):
                with patch.object(
                    loop, "_run_sandbox_if_configured",
                    new_callable=AsyncMock, return_value=None,
                ):
                    await loop._handle_task_completion(
                        "pipeline-1", 1, True, "team-1"
                    )

        assert mock_task.status == "done"
        assert mock_task.completed_at is not None

    @pytest.mark.asyncio
    async def test_retry_resets_to_todo(self):
        """Failed task with retries remaining is reset to todo."""
        mock_task = _make_ptask(retry_count=0)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_task)
        mock_db.commit = AsyncMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
            with patch("openclaw.services.execution_loop.settings") as mock_settings:
                mock_settings.max_task_retries = 2
                with patch.object(loop, "_publish_event", new_callable=AsyncMock):
                    await loop._handle_task_completion(
                        "pipeline-1", 1, False, "team-1"
                    )

        assert mock_task.status == "todo"
        assert mock_task.retry_count == 1
        assert mock_task.agent_id is None
        assert mock_task.started_at is None

    @pytest.mark.asyncio
    async def test_retry_increments_count(self):
        """Each retry increments the retry count."""
        mock_task = _make_ptask(retry_count=1)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_task)
        mock_db.commit = AsyncMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
            with patch("openclaw.services.execution_loop.settings") as mock_settings:
                mock_settings.max_task_retries = 3
                with patch.object(loop, "_publish_event", new_callable=AsyncMock):
                    await loop._handle_task_completion(
                        "pipeline-1", 1, False, "team-1"
                    )

        assert mock_task.retry_count == 2
        assert mock_task.status == "todo"

    @pytest.mark.asyncio
    async def test_max_retries_fails_task(self):
        """When max retries exceeded, task is marked failed."""
        mock_task = _make_ptask(retry_count=2)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_task)
        mock_db.commit = AsyncMock()

        mock_events = MagicMock()
        mock_events.append = AsyncMock()

        loop = ExecutionLoop(session_factory=_make_mock_session_factory(mock_db))

        with patch("openclaw.services.execution_loop.EventStore", return_value=mock_events):
            with patch("openclaw.services.execution_loop.settings") as mock_settings:
                mock_settings.max_task_retries = 2
                with patch.object(loop, "_publish_event", new_callable=AsyncMock):
                    await loop._handle_task_completion(
                        "pipeline-1", 1, False, "team-1"
                    )

        assert mock_task.status == "failed"
        assert mock_task.completed_at is not None
