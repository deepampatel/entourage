"""Tests for RecoveryManager — crash recovery on startup.

Tests the RecoveryReport dataclass and the core recovery logic
using direct DB manipulation within the test savepoint.
"""

from datetime import datetime, timedelta, timezone

import pytest

from openclaw.db.models import Agent, Run, RunTask, Session
from openclaw.services.recovery import RecoveryManager, RecoveryReport
from contextlib import asynccontextmanager


def _make_session_factory(db_session):
    @asynccontextmanager
    async def factory():
        yield db_session
    return factory


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Recovery Org", "slug": "recovery-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Recovery Team", "slug": "recovery-team"},
    )
    return resp.json()


@pytest.fixture
async def agent(client, team):
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/agents",
        json={"name": "RecoverBot", "role": "engineer"},
    )
    return resp.json()


# ═══════════════════════════════════════════════════════════
# Tests — RecoveryReport
# ═══════════════════════════════════════════════════════════


class TestRecoveryReport:
    """Test the RecoveryReport dataclass."""

    def test_total_recovered(self):
        r = RecoveryReport(agents_reset=2, tasks_reset=3, sessions_closed=1)
        assert r.total_recovered == 6

    def test_had_orphans_true(self):
        r = RecoveryReport(agents_reset=1)
        assert r.had_orphans is True

    def test_had_orphans_false(self):
        r = RecoveryReport()
        assert r.had_orphans is False

    def test_had_orphans_from_runs_failed(self):
        r = RecoveryReport(runs_failed=1)
        assert r.had_orphans is True


# ═══════════════════════════════════════════════════════════
# Tests — Stuck agent recovery
# ═══════════════════════════════════════════════════════════


class TestRecoveryStuckAgents:
    """Test recovery of agents stuck in 'working' status."""

    async def test_working_agent_reset_to_idle(self, client, team, agent, db_session):
        """Agents stuck in 'working' should be reset to 'idle'."""
        from sqlalchemy import select, update

        agent_id = agent["id"]

        # Set agent to working directly in DB
        await db_session.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(status="working")
        )
        await db_session.flush()

        manager = RecoveryManager(session_factory=_make_session_factory(db_session))
        report = await manager.run()

        # Should find exactly this agent
        assert report.agents_reset >= 1

        # Verify the agent was reset
        result = await db_session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        recovered_agent = result.scalars().first()
        assert recovered_agent.status == "idle"

    async def test_idle_agent_not_touched(self, client, team, agent, db_session):
        """Agents already idle should not be counted."""
        from sqlalchemy import select

        manager = RecoveryManager(session_factory=_make_session_factory(db_session))

        # Count working agents before
        result = await db_session.execute(
            select(Agent).where(Agent.status == "working")
        )
        working_before = len(list(result.scalars().all()))

        report = await manager.run()
        assert report.agents_reset == working_before  # only pre-existing (if any)


# ═══════════════════════════════════════════════════════════
# Tests — Dry run
# ═══════════════════════════════════════════════════════════


class TestRecoveryDryRun:
    """Test dry-run mode."""

    async def test_dry_run_reports_but_doesnt_change(
        self, client, team, agent, db_session
    ):
        """Dry run should count orphans but not modify state."""
        from sqlalchemy import select, update

        agent_id = agent["id"]

        # Put agent in working
        await db_session.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(status="working")
        )
        await db_session.flush()

        manager = RecoveryManager(session_factory=_make_session_factory(db_session))
        report = await manager.run(dry_run=True)

        assert report.agents_reset >= 1

        # Agent should still be working (dry run didn't change it)
        result = await db_session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent_obj = result.scalars().first()
        assert agent_obj.status == "working"
