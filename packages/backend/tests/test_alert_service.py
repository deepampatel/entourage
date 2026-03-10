"""Tests for AlertService — budget, failure, and performance alerting.

Covers: budget threshold checks, deduplication, failure spike detection,
performance anomaly detection, alert acknowledgement.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.alert_service import AlertData, AlertService


# ═══════════════════════════════════════════════════════════
# AlertData tests
# ═══════════════════════════════════════════════════════════


def test_alert_data_dataclass():
    """AlertData dataclass serializes correctly."""
    alert = AlertData(
        kind="budget_warning",
        team_id="team-1",
        org_id="org-1",
        severity="warning",
        message="80% budget used",
        data={"ratio": 0.8},
    )
    assert alert.kind == "budget_warning"
    assert alert.severity == "warning"
    assert alert.data["ratio"] == 0.8


def test_alert_data_default_data():
    """AlertData defaults to empty dict for data field."""
    alert = AlertData(
        kind="test",
        team_id="t",
        org_id="o",
        severity="warning",
        message="test",
    )
    assert alert.data == {}


# ═══════════════════════════════════════════════════════════
# Budget check tests (mocked)
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_no_alert_under_budget():
    """No alert when spend is below warning threshold."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"
    team.org_id = "org-id"

    org = MagicMock()
    org.id = "org-id"
    org.config = {"monthly_budget_cap_usd": 500.0, "budget_warning_threshold": 0.8}

    # Mock DB queries
    db.get = AsyncMock(side_effect=lambda model, id: team if model.__name__ == "Team" else org)

    # Mock budget query - spend is $100 / $500 = 20%
    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 100.0
    db.execute = AsyncMock(return_value=scalar_result)

    svc = AlertService(db)
    alerts = await svc._check_budget(team, org)
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_budget_warning_at_threshold():
    """Warning alert fires at 80% of budget cap."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"
    org.config = {"monthly_budget_cap_usd": 500.0, "budget_warning_threshold": 0.8}

    # Mock budget query - spend is $420 / $500 = 84%
    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 420.0
    db.execute = AsyncMock(return_value=scalar_result)

    svc = AlertService(db)
    alerts = await svc._check_budget(team, org)
    assert len(alerts) == 1
    assert alerts[0].kind == "budget_warning"
    assert alerts[0].severity == "warning"


@pytest.mark.asyncio
async def test_budget_exceeded():
    """Critical alert fires at 100%+ of budget cap."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"
    org.config = {"monthly_budget_cap_usd": 500.0, "budget_warning_threshold": 0.8}

    # Mock budget query - spend is $550 / $500 = 110%
    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 550.0
    db.execute = AsyncMock(return_value=scalar_result)

    svc = AlertService(db)
    alerts = await svc._check_budget(team, org)
    assert len(alerts) == 1
    assert alerts[0].kind == "budget_exceeded"
    assert alerts[0].severity == "critical"


@pytest.mark.asyncio
async def test_no_budget_alert_without_cap():
    """No alert when org has no monthly_budget_cap_usd configured."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"
    org.config = {}  # No cap

    svc = AlertService(db)
    alerts = await svc._check_budget(team, org)
    assert len(alerts) == 0


# ═══════════════════════════════════════════════════════════
# Failure spike tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_failure_spike_detection():
    """Alert after 3+ consecutive run failures."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"

    # Mock query result - 4 consecutive failures
    rows = MagicMock()
    rows.all.return_value = [("failed",), ("failed",), ("failed",), ("failed",), ("done",)]
    db.execute = AsyncMock(return_value=rows)

    svc = AlertService(db)
    alerts = await svc._check_failure_rate(team, org)
    assert len(alerts) == 1
    assert alerts[0].kind == "failure_spike"
    assert alerts[0].data["consecutive_failures"] == 4


@pytest.mark.asyncio
async def test_no_failure_spike_with_success():
    """No alert when recent run succeeded."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"

    # Most recent is done, followed by failures
    rows = MagicMock()
    rows.all.return_value = [("done",), ("failed",), ("failed",), ("failed",)]
    db.execute = AsyncMock(return_value=rows)

    svc = AlertService(db)
    alerts = await svc._check_failure_rate(team, org)
    assert len(alerts) == 0


# ═══════════════════════════════════════════════════════════
# Performance tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_performance_anomaly():
    """Alert when recent avg duration > 2x baseline."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"

    # First call: baseline avg (30-day) = 100s
    # Second call: recent avg (7-day) = 250s (2.5x)
    call_count = 0
    async def mock_execute(q):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar.return_value = 100.0 if call_count == 1 else 250.0
        return result

    db.execute = mock_execute

    svc = AlertService(db)
    alerts = await svc._check_performance(team, org)
    assert len(alerts) == 1
    assert alerts[0].kind == "performance"
    assert alerts[0].data["ratio"] == 2.5


@pytest.mark.asyncio
async def test_no_performance_alert_normal():
    """No alert when recent avg is within normal range."""
    db = AsyncMock()

    team = MagicMock()
    team.id = "team-id"

    org = MagicMock()
    org.id = "org-id"

    # Both queries return similar durations
    call_count = 0
    async def mock_execute(q):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar.return_value = 100.0 if call_count == 1 else 150.0
        return result

    db.execute = mock_execute

    svc = AlertService(db)
    alerts = await svc._check_performance(team, org)
    assert len(alerts) == 0


# ═══════════════════════════════════════════════════════════
# Deduplication tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_alert_deduplication():
    """Same alert kind within 1 hour is not re-fired."""
    db = AsyncMock()

    # Mock: existing alert of same kind in last hour
    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 1  # 1 existing alert
    db.execute = AsyncMock(return_value=scalar_result)

    alert_data = AlertData(
        kind="budget_warning",
        team_id="team-id",
        org_id="org-id",
        severity="warning",
        message="test",
    )

    svc = AlertService(db)
    is_dup = await svc._is_duplicate(alert_data)
    assert is_dup is True


@pytest.mark.asyncio
async def test_alert_not_duplicate_after_expiry():
    """Alert is not duplicate when no matching alert in last hour."""
    db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 0  # No existing alerts
    db.execute = AsyncMock(return_value=scalar_result)

    alert_data = AlertData(
        kind="budget_warning",
        team_id="team-id",
        org_id="org-id",
        severity="warning",
        message="test",
    )

    svc = AlertService(db)
    is_dup = await svc._is_duplicate(alert_data)
    assert is_dup is False
