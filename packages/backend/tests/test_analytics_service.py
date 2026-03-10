"""Tests for AnalyticsService — read-only aggregation queries."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.analytics_service import AnalyticsService, _period_start


# ─── Helpers ─────────────────────────────────────────────────


def _make_run(status="done", cost=1.5, created_days_ago=3, duration_hours=2):
    """Create a mock Run object."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=created_days_ago)
    completed = created + timedelta(hours=duration_hours) if status == "done" else None

    p = MagicMock()
    p.status = status
    p.actual_cost_usd = cost
    p.created_at = created
    p.completed_at = completed
    p.id = uuid.uuid4()
    p.title = f"Run {status}"
    return p


def _make_agent(name="agent-1", role="engineer"):
    a = MagicMock()
    a.id = uuid.uuid4()
    a.name = name
    a.role = role
    a.team_id = uuid.uuid4()
    return a


def _make_session(cost=0.5, tokens_in=1000, tokens_out=500, cache_read=200,
                  duration_minutes=10, task_id=1, agent_id=None):
    now = datetime.now(timezone.utc)
    s = MagicMock()
    s.agent_id = agent_id or uuid.uuid4()
    s.cost_usd = cost
    s.tokens_in = tokens_in
    s.tokens_out = tokens_out
    s.cache_read = cache_read
    s.cache_write = 0
    s.task_id = task_id
    s.started_at = now - timedelta(minutes=duration_minutes)
    s.ended_at = now
    return s


def _make_run_task(status="done", agent_id=None):
    t = MagicMock()
    t.id = 1
    t.status = status
    t.agent_id = agent_id or uuid.uuid4()
    t.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    t.title = f"Task {status}"
    return t


def _make_budget_entry(cost=0.25, tokens_in=500, tokens_out=100,
                       task_id=1, agent_id=None):
    e = MagicMock()
    e.cost_usd = cost
    e.input_tokens = tokens_in
    e.output_tokens = tokens_out
    e.run_task_id = task_id
    e.agent_id = agent_id or uuid.uuid4()
    e.recorded_at = datetime.now(timezone.utc)
    e.run_id = uuid.uuid4()
    return e


class _MockScalars:
    """Mock for db.execute().scalars()."""

    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _MockResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return _MockScalars(self._items)


# ─── Period start tests ──────────────────────────────────────


def test_period_start_day():
    start = _period_start("day")
    now = datetime.now(timezone.utc)
    # Should be roughly 24 hours ago
    diff = (now - start).total_seconds()
    assert 86300 < diff < 86500


def test_period_start_week():
    start = _period_start("week")
    now = datetime.now(timezone.utc)
    diff = (now - start).total_seconds()
    assert 604700 < diff < 604900


def test_period_start_all():
    start = _period_start("all")
    assert start.year == 2020


# ─── Run metrics ────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_metrics_empty_team():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_MockResult([]))
    svc = AnalyticsService(db)

    result = await svc.get_run_metrics(uuid.uuid4(), "week")

    assert result["total_runs"] == 0
    assert result["success_rate"] == 0.0
    assert result["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_run_metrics_counts_by_status():
    runs = [
        _make_run(status="done", cost=1.0),
        _make_run(status="done", cost=2.0),
        _make_run(status="failed", cost=0.5),
        _make_run(status="cancelled", cost=0.0),
        _make_run(status="executing", cost=0.3),
    ]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_MockResult(runs))
    svc = AnalyticsService(db)

    result = await svc.get_run_metrics(uuid.uuid4(), "week")

    assert result["total_runs"] == 5
    assert result["completed"] == 2
    assert result["failed"] == 1
    assert result["cancelled"] == 1
    assert result["in_progress"] == 1
    # Success rate: 2 / (2 + 1 + 1) = 50%
    assert result["success_rate"] == 50.0
    assert result["total_cost_usd"] == 3.8


@pytest.mark.asyncio
async def test_run_metrics_success_rate_excludes_in_progress():
    """Only terminal states (done, failed, cancelled) count for success rate."""
    runs = [
        _make_run(status="done", cost=1.0),
        _make_run(status="executing", cost=0.5),
    ]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_MockResult(runs))
    svc = AnalyticsService(db)

    result = await svc.get_run_metrics(uuid.uuid4(), "week")

    # Only 1 terminal (done), so success_rate = 100%
    assert result["success_rate"] == 100.0


# ─── Agent performance ───────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_performance_ranking():
    agent1 = _make_agent("alice", "engineer")
    agent2 = _make_agent("bob", "engineer")

    sessions1 = [_make_session(cost=2.0, tokens_in=1000, cache_read=500, agent_id=agent1.id)]
    sessions2 = [_make_session(cost=0.5, tokens_in=800, cache_read=100, agent_id=agent2.id)]

    tasks1 = [_make_run_task("done", agent1.id)]
    tasks2 = [_make_run_task("failed", agent2.id)]

    call_count = 0
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        # Call order: agents, then for each agent: sessions, tasks
        if call_count == 1:
            return _MockResult([agent1, agent2])
        elif call_count == 2:
            return _MockResult(sessions1)
        elif call_count == 3:
            return _MockResult(tasks1)
        elif call_count == 4:
            return _MockResult(sessions2)
        elif call_count == 5:
            return _MockResult(tasks2)
        return _MockResult([])

    db = AsyncMock()
    db.execute = mock_execute
    svc = AnalyticsService(db)

    result = await svc.get_agent_performance(uuid.uuid4(), "week")

    assert len(result) == 2
    # Sorted by cost desc, alice (2.0) first
    assert result[0]["agent_name"] == "alice"
    assert result[0]["total_cost_usd"] == 2.0
    assert result[0]["tasks_completed"] == 1
    assert result[0]["success_rate"] == 100.0

    assert result[1]["agent_name"] == "bob"
    assert result[1]["total_cost_usd"] == 0.5
    assert result[1]["tasks_failed"] == 1
    assert result[1]["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_cache_hit_rate_calculation():
    agent = _make_agent("alice", "engineer")
    # tokens_in=800, cache_read=200 -> cache_hit = 200/(800+200) = 20%
    sessions = [_make_session(tokens_in=800, cache_read=200, agent_id=agent.id)]

    call_count = 0
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockResult([agent])
        elif call_count == 2:
            return _MockResult(sessions)
        elif call_count == 3:
            return _MockResult([])
        return _MockResult([])

    db = AsyncMock()
    db.execute = mock_execute
    svc = AnalyticsService(db)

    result = await svc.get_agent_performance(uuid.uuid4(), "week")

    assert result[0]["cache_hit_rate"] == 20.0


# ─── Cost timeseries ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_cost_timeseries_daily_buckets():
    now = datetime.now(timezone.utc)
    s1 = _make_session(cost=1.0)
    s1.started_at = now - timedelta(days=1)
    s2 = _make_session(cost=2.0)
    s2.started_at = now - timedelta(days=1)
    s3 = _make_session(cost=0.5)
    s3.started_at = now

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_MockResult([s1, s2, s3]))
    svc = AnalyticsService(db)

    result = await svc.get_cost_timeseries(uuid.uuid4(), "day", 7)

    assert len(result) == 2  # Two distinct days
    # Sorted by period
    assert result[0]["cost_usd"] == 3.0  # s1 + s2
    assert result[0]["session_count"] == 2
    assert result[1]["cost_usd"] == 0.5  # s3


@pytest.mark.asyncio
async def test_cost_timeseries_respects_days_filter():
    """Only sessions within the specified day range should be included."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_MockResult([]))
    svc = AnalyticsService(db)

    result = await svc.get_cost_timeseries(uuid.uuid4(), "day", 7)

    assert result == []


# ─── Run cost detail ────────────────────────────────────


@pytest.mark.asyncio
async def test_run_cost_detail():
    run_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    run = _make_run(status="done", cost=1.5)
    run.id = run_id
    run.title = "Test Run"
    run.actual_cost_usd = 1.5

    task = _make_run_task("done", agent_id)
    task.id = 1
    task.title = "Implement feature"
    task.run_id = run_id

    entry = _make_budget_entry(cost=1.5, task_id=1, agent_id=agent_id)
    entry.run_id = run_id

    agent_mock = MagicMock()
    agent_mock.id = agent_id
    agent_mock.name = "alice"

    call_count = 0
    async def mock_execute(query):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # Run
            return _MockResult([run])
        elif call_count == 2:  # Budget entries
            return _MockResult([entry])
        elif call_count == 3:  # Run tasks
            return _MockResult([task])
        elif call_count == 4:  # Agents
            return _MockResult([agent_mock])
        return _MockResult([])

    db = AsyncMock()
    db.execute = mock_execute
    svc = AnalyticsService(db)

    result = await svc.get_run_cost_detail(run_id)

    assert result["run_id"] == run_id
    assert result["title"] == "Test Run"
    assert result["total_cost_usd"] == 1.5
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["cost_usd"] == 1.5


# ─── Monthly rollup ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_rollup():
    now = datetime.now(timezone.utc)
    s1 = _make_session(cost=3.0)
    s1.started_at = now.replace(day=1)
    s2 = _make_session(cost=2.0)
    s2.started_at = (now - timedelta(days=35)).replace(day=15)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_MockResult([s2, s1]))
    svc = AnalyticsService(db)

    result = await svc.get_monthly_rollup(uuid.uuid4(), months=6)

    assert len(result) == 2
    # Sorted by month ascending
    assert result[0]["total_cost_usd"] == 2.0
    assert result[1]["total_cost_usd"] == 3.0
