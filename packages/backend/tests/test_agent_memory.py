"""Tests for AgentMemoryManager service."""

import os
from pathlib import Path

import pytest

from openclaw.services.agent_memory import AgentMemoryManager


@pytest.fixture
def worktree(tmp_path):
    """Create a temporary worktree directory."""
    return str(tmp_path / "worktree")


@pytest.fixture
def memory_mgr():
    return AgentMemoryManager()


class TestWriteReflection:
    @pytest.mark.asyncio
    async def test_creates_openclaw_dir(self, memory_mgr, worktree):
        await memory_mgr.write_reflection(
            agent_id="agent-1",
            run_task_id=1,
            reflection="Learned to use pytest fixtures",
            worktree_path=worktree,
        )
        assert (Path(worktree) / ".openclaw").is_dir()

    @pytest.mark.asyncio
    async def test_creates_reflections_file(self, memory_mgr, worktree):
        path = await memory_mgr.write_reflection(
            agent_id="agent-1",
            run_task_id=1,
            reflection="Test reflection",
            worktree_path=worktree,
        )
        assert os.path.exists(path)
        content = Path(path).read_text()
        assert "Test reflection" in content
        assert "agent-1" in content
        assert "Task #1" in content

    @pytest.mark.asyncio
    async def test_appends_multiple_reflections(self, memory_mgr, worktree):
        await memory_mgr.write_reflection(
            "agent-1", 1, "First reflection", worktree
        )
        await memory_mgr.write_reflection(
            "agent-1", 2, "Second reflection", worktree
        )

        filepath = Path(worktree) / ".openclaw" / "reflections.md"
        content = filepath.read_text()
        assert "First reflection" in content
        assert "Second reflection" in content
        assert content.count("---") == 2


class TestWriteFeedback:
    @pytest.mark.asyncio
    async def test_creates_feedback_file(self, memory_mgr, worktree):
        path = await memory_mgr.write_feedback(
            agent_id="agent-1",
            run_task_id=1,
            feedback="Fix the error handling",
            worktree_path=worktree,
        )
        assert os.path.exists(path)
        content = Path(path).read_text()
        assert "Fix the error handling" in content
        assert "Feedback for Task #1" in content


class TestGetMemoryContext:
    @pytest.mark.asyncio
    async def test_empty_when_no_files(self, memory_mgr, worktree):
        result = await memory_mgr.get_memory_context("agent-1", worktree)
        assert result["reflections"] == ""
        assert result["feedback"] == ""

    @pytest.mark.asyncio
    async def test_reads_existing_files(self, memory_mgr, worktree):
        await memory_mgr.write_reflection(
            "agent-1", 1, "My reflection", worktree
        )
        await memory_mgr.write_feedback(
            "agent-1", 1, "Some feedback", worktree
        )

        result = await memory_mgr.get_memory_context("agent-1", worktree)
        assert "My reflection" in result["reflections"]
        assert "Some feedback" in result["feedback"]


class TestInjectMemory:
    @pytest.mark.asyncio
    async def test_no_memory_returns_base_prompt(self, memory_mgr, worktree):
        result = await memory_mgr.inject_memory_into_prompt(
            "Do the task", "agent-1", worktree
        )
        assert result == "Do the task"

    @pytest.mark.asyncio
    async def test_injects_reflections(self, memory_mgr, worktree):
        await memory_mgr.write_reflection(
            "agent-1", 1, "Important lesson", worktree
        )

        result = await memory_mgr.inject_memory_into_prompt(
            "Do the task", "agent-1", worktree
        )
        assert "Do the task" in result
        assert "Previous Reflections" in result
        assert "Important lesson" in result

    @pytest.mark.asyncio
    async def test_injects_feedback(self, memory_mgr, worktree):
        await memory_mgr.write_feedback(
            "agent-1", 1, "Fix the bug", worktree
        )

        result = await memory_mgr.inject_memory_into_prompt(
            "Do the task", "agent-1", worktree
        )
        assert "Feedback From Reviewers" in result
        assert "Fix the bug" in result

    @pytest.mark.asyncio
    async def test_injects_both(self, memory_mgr, worktree):
        await memory_mgr.write_reflection(
            "agent-1", 1, "Lesson learned", worktree
        )
        await memory_mgr.write_feedback(
            "agent-1", 1, "Good work", worktree
        )

        result = await memory_mgr.inject_memory_into_prompt(
            "Base prompt", "agent-1", worktree
        )
        assert "Base prompt" in result
        assert "Lesson learned" in result
        assert "Good work" in result
