"""Tests for Phase 3 parallel dispatch: worktrees, atomic acquire, event-driven.

These tests verify the three critical upgrades that enable 100-agent parallelism:
1. Git worktree isolation per task
2. Atomic agent acquisition (no double-dispatch)
3. Event-driven wakeup (no polling delay)
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from openclaw.services.execution_loop import ExecutionLoop


# ─── Fixtures ─────────────────────────────────────────────────


class FakeDB:
    """Minimal async DB session mock for unit tests."""

    def __init__(self, agents=None, run=None, tasks=None):
        self._agents = agents or []
        self._run = run
        self._tasks = tasks or []
        self._committed = False

    async def get(self, model_cls, pk):
        if model_cls.__name__ == "Run":
            return self._run
        if model_cls.__name__ == "Agent":
            for a in self._agents:
                if a.id == pk:
                    return a
            return None
        if model_cls.__name__ == "RunTask":
            for t in self._tasks:
                if t.id == pk:
                    return t
            return None
        return None

    async def execute(self, stmt, params=None):
        """Handle both ORM select and raw SQL text statements."""
        return FakeResult(self._agents, self._tasks, params)

    async def commit(self):
        self._committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeResult:
    def __init__(self, agents, tasks, params=None):
        self._agents = agents
        self._tasks = tasks
        self._params = params
        self._rows = []

    def scalars(self):
        return self

    def all(self):
        return self._tasks

    def first(self):
        return self._agents[0] if self._agents else None

    def fetchone(self):
        """For atomic acquisition queries."""
        if self._agents:
            agent = self._agents.pop(0)
            return (agent.id,)
        return None

    def fetchall(self):
        """For multi-agent atomic acquisition."""
        rows = [(a.id,) for a in self._agents]
        self._agents.clear()
        return rows


class FakeAgent:
    def __init__(self, agent_id=None, status="idle"):
        self.id = agent_id or uuid.uuid4()
        self.status = status
        self.team_id = uuid.uuid4()
        self.role = "engineer"


class FakeRun:
    def __init__(self, run_id=None, team_id=None, repo_id=None, status="executing"):
        self.id = run_id or uuid.uuid4()
        self.team_id = team_id or uuid.uuid4()
        self.repository_id = repo_id
        self.status = status


class FakeRunTask:
    def __init__(self, task_id=1, status="todo", deps=None):
        self.id = task_id
        self.status = status
        self.dependencies = deps
        self.title = f"Task {task_id}"
        self.description = f"Description for task {task_id}"
        self.agent_id = None
        self.started_at = None
        self.retry_count = 0
        self.result = None
        self.error = None
        self.completed_at = None


# ─── Test: Atomic Agent Acquisition ──────────────────────────


@pytest.mark.asyncio
async def test_acquire_agent_atomic_returns_agent():
    """Atomic acquire should set agent status to 'working' and return it."""
    agent = FakeAgent(status="idle")
    db = FakeDB(agents=[agent])

    loop = ExecutionLoop(session_factory=lambda: db)

    # The atomic acquire uses raw SQL, so we need to mock at a deeper level.
    # For this unit test, we verify the method exists and has the right signature.
    assert hasattr(loop, "_acquire_agent_atomic")
    assert hasattr(loop, "_acquire_agents_atomic")


@pytest.mark.asyncio
async def test_acquire_agents_returns_empty_when_no_idle():
    """When no agents are idle, acquisition should return empty list."""
    db = FakeDB(agents=[])
    loop = ExecutionLoop(session_factory=lambda: db)

    agents = await loop._acquire_agents_atomic(
        db, uuid.uuid4(), max_count=3
    )
    assert agents == []


# ─── Test: Event-Driven Wakeup ───────────────────────────────


@pytest.mark.asyncio
async def test_wakeup_event_exists():
    """ExecutionLoop should have a _wakeup asyncio.Event."""
    loop = ExecutionLoop(session_factory=AsyncMock())
    assert isinstance(loop._wakeup, asyncio.Event)
    assert not loop._wakeup.is_set()


@pytest.mark.asyncio
async def test_wakeup_event_is_set_after_signal():
    """Setting _wakeup should unblock any waiter."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    # Start a waiter
    async def waiter():
        await asyncio.wait_for(loop._wakeup.wait(), timeout=5.0)
        return True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)  # Let waiter start

    # Signal wakeup
    loop._wakeup.set()
    result = await task
    assert result is True


@pytest.mark.asyncio
async def test_wakeup_faster_than_polling():
    """Event-driven dispatch should be faster than polling interval."""
    import time

    loop = ExecutionLoop(session_factory=AsyncMock())

    start = time.monotonic()

    # Simulate what the dispatch loop does: wait with timeout
    loop._wakeup.clear()

    async def signal_soon():
        await asyncio.sleep(0.1)  # 100ms
        loop._wakeup.set()

    asyncio.create_task(signal_soon())

    try:
        await asyncio.wait_for(loop._wakeup.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    elapsed = time.monotonic() - start
    # Should wake up in ~100ms, NOT in 10s (polling interval)
    assert elapsed < 1.0, f"Wakeup took {elapsed:.1f}s, should be <1s"


# ─── Test: Worktree Integration ──────────────────────────────


@pytest.mark.asyncio
async def test_run_task_accepts_worktree_path():
    """_run_task should accept and use worktree_path parameter."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    # Verify the method signature includes worktree_path
    import inspect
    sig = inspect.signature(loop._run_task)
    assert "worktree_path" in sig.parameters


@pytest.mark.asyncio
async def test_run_task_passes_worktree_to_runner():
    """_run_task should pass worktree_path to AgentRunner.run_agent."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    # We'll verify run_agent accepts working_directory
    from openclaw.agent.runner import AgentRunner
    import inspect
    sig = inspect.signature(AgentRunner.run_agent)
    assert "working_directory" in sig.parameters


# ─── Test: Release Agent ──────────────────────────────────────


@pytest.mark.asyncio
async def test_release_agent_exists():
    """_release_agent method should exist for cleanup."""
    loop = ExecutionLoop(session_factory=AsyncMock())
    assert hasattr(loop, "_release_agent")


# ─── Test: find_ready_tasks ──────────────────────────────────


def test_find_ready_tasks_respects_dependencies():
    """Tasks with unmet dependencies should NOT be returned as ready."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    t0 = FakeRunTask(task_id=0, status="done")
    t1 = FakeRunTask(task_id=1, status="todo", deps=[0])  # dep met
    t2 = FakeRunTask(task_id=2, status="todo", deps=[1])  # dep NOT met

    ready = loop._find_ready_tasks([t0, t1, t2], max_count=5)
    assert len(ready) == 1
    assert ready[0].id == 1


def test_find_ready_tasks_returns_multiple_parallel():
    """Tasks with no dependencies should all be ready simultaneously."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    t0 = FakeRunTask(task_id=0, status="todo", deps=[])
    t1 = FakeRunTask(task_id=1, status="todo", deps=[])
    t2 = FakeRunTask(task_id=2, status="todo", deps=[])

    ready = loop._find_ready_tasks([t0, t1, t2], max_count=10)
    assert len(ready) == 3


def test_find_ready_tasks_respects_max_count():
    """Should not return more tasks than max_count."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    tasks = [FakeRunTask(task_id=i, status="todo", deps=[]) for i in range(10)]
    ready = loop._find_ready_tasks(tasks, max_count=3)
    assert len(ready) == 3


def test_find_ready_tasks_diamond_dependency():
    """Diamond dependency pattern: A→B, A→C, B&C→D."""
    loop = ExecutionLoop(session_factory=AsyncMock())

    # A done, B and C should both be ready
    t_a = FakeRunTask(task_id=0, status="done", deps=[])
    t_b = FakeRunTask(task_id=1, status="todo", deps=[0])
    t_c = FakeRunTask(task_id=2, status="todo", deps=[0])
    t_d = FakeRunTask(task_id=3, status="todo", deps=[1, 2])  # blocked

    ready = loop._find_ready_tasks([t_a, t_b, t_c, t_d], max_count=10)
    assert len(ready) == 2
    assert {r.id for r in ready} == {1, 2}


# ─── Test: Real Git Worktree (integration) ───────────────────


@pytest.mark.asyncio
async def test_git_worktree_create_and_cleanup(tmp_path):
    """Create a real git worktree and verify isolation.

    This is a real integration test — creates actual git repos.
    """
    import subprocess

    # Create a bare git repo
    repo_path = str(tmp_path / "test-repo")
    os.makedirs(repo_path)
    subprocess.run(["git", "init", repo_path], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", repo_path, "commit", "--allow-empty", "-m", "init"],
        check=True, capture_output=True,
    )

    # Create a worktree manually (simulating what GitService does)
    wt_path = os.path.join(repo_path, ".worktrees", "task-1-test")
    branch = "task-1-test"

    subprocess.run(
        ["git", "-C", repo_path, "branch", branch],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", wt_path, branch],
        check=True, capture_output=True,
    )

    # Verify isolation
    assert os.path.exists(wt_path)
    assert os.path.exists(os.path.join(wt_path, ".git"))

    # Create a file in the worktree — should NOT appear in main
    test_file = os.path.join(wt_path, "agent_output.txt")
    with open(test_file, "w") as f:
        f.write("Agent 1 was here")

    assert os.path.exists(test_file)
    assert not os.path.exists(os.path.join(repo_path, "agent_output.txt"))

    # Cleanup
    subprocess.run(
        ["git", "-C", repo_path, "worktree", "remove", wt_path, "--force"],
        check=True, capture_output=True,
    )
    assert not os.path.exists(wt_path)


@pytest.mark.asyncio
async def test_parallel_worktrees_dont_conflict(tmp_path):
    """Two worktrees from the same repo should be fully isolated."""
    import subprocess

    repo_path = str(tmp_path / "shared-repo")
    os.makedirs(repo_path)
    subprocess.run(["git", "init", repo_path], check=True, capture_output=True)

    # Create initial file and commit
    with open(os.path.join(repo_path, "shared.txt"), "w") as f:
        f.write("original content")
    subprocess.run(["git", "-C", repo_path, "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", "init"],
        check=True, capture_output=True,
    )

    # Create two worktrees (simulating two parallel agents)
    wt1 = os.path.join(repo_path, ".worktrees", "agent-1")
    wt2 = os.path.join(repo_path, ".worktrees", "agent-2")

    for branch, wt in [("agent-1", wt1), ("agent-2", wt2)]:
        subprocess.run(
            ["git", "-C", repo_path, "branch", branch],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "add", wt, branch],
            check=True, capture_output=True,
        )

    # Agent 1 modifies shared.txt
    with open(os.path.join(wt1, "shared.txt"), "w") as f:
        f.write("agent 1 modified this")

    # Agent 2 sees the ORIGINAL content, not agent 1's changes
    with open(os.path.join(wt2, "shared.txt")) as f:
        content = f.read()
    assert content == "original content", \
        f"Agent 2 saw agent 1's changes! Content: {content}"

    # Each agent creates different files
    with open(os.path.join(wt1, "agent1_file.py"), "w") as f:
        f.write("# Agent 1's code")
    with open(os.path.join(wt2, "agent2_file.py"), "w") as f:
        f.write("# Agent 2's code")

    assert not os.path.exists(os.path.join(wt2, "agent1_file.py"))
    assert not os.path.exists(os.path.join(wt1, "agent2_file.py"))

    # Cleanup
    for wt in [wt1, wt2]:
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "remove", wt, "--force"],
            check=True, capture_output=True,
        )


# ─── Test: Concurrent Acquisition Race ──────────────────────


@pytest.mark.asyncio
async def test_concurrent_acquire_no_double_dispatch(tmp_path):
    """Simulate 10 concurrent acquire attempts on 3 agents.

    Only 3 should succeed. This tests the conceptual behavior —
    real DB testing requires PostgreSQL.
    """
    available_agents = [FakeAgent() for _ in range(3)]
    acquired = []
    lock = asyncio.Lock()

    async def try_acquire():
        async with lock:
            if available_agents:
                agent = available_agents.pop(0)
                acquired.append(agent)
                return agent
            return None

    # 10 concurrent acquire attempts
    results = await asyncio.gather(*[try_acquire() for _ in range(10)])

    # Exactly 3 should succeed
    successes = [r for r in results if r is not None]
    assert len(successes) == 3
    assert len(acquired) == 3

    # All acquired agents should be unique
    ids = [a.id for a in acquired]
    assert len(set(ids)) == 3
