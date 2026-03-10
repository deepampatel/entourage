"""Tests for SecurityEnforcer — write-path, network, bash validation.

Covers: write-path enforcement, network allowlist matching (exact + wildcard),
bash command denial, violation persistence, strict vs permissive mode,
and API query helpers.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.security_enforcer import SecurityEnforcer, SecurityViolation


# ═══════════════════════════════════════════════════════════
# SecurityViolation dataclass tests
# ═══════════════════════════════════════════════════════════


def test_security_violation_dataclass():
    """SecurityViolation stores all required fields."""
    v = SecurityViolation(
        kind="write_path",
        agent_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        run_task_id=42,
        detail="/etc/passwd",
        rule="outside_worktree",
        action="blocked",
    )
    assert v.kind == "write_path"
    assert v.action == "blocked"
    assert v.run_task_id == 42


def test_security_violation_nullable_task():
    """SecurityViolation works without run_task_id."""
    v = SecurityViolation(
        kind="network",
        agent_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        run_task_id=None,
        detail="evil.com",
        rule="not_in_allowlist",
        action="logged",
    )
    assert v.run_task_id is None


# ═══════════════════════════════════════════════════════════
# Write path validation tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_write_path_within_worktree_allowed():
    """Write to a file inside the worktree is allowed (no violation)."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_write_path(
        path="/workspace/project/src/main.py",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowed_paths=["/workspace/project"],
    )
    assert result is None  # No violation


@pytest.mark.asyncio
async def test_write_path_outside_worktree_blocked():
    """Write to /etc is blocked."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_write_path(
        path="/etc/passwd",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowed_paths=["/workspace/project"],
    )
    assert result is not None
    assert result.kind == "write_path"
    assert result.action == "blocked"


@pytest.mark.asyncio
async def test_write_path_parent_traversal_blocked():
    """Parent directory traversal (../../) attack is caught."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_write_path(
        path="/workspace/project/../../etc/passwd",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowed_paths=["/workspace/project"],
    )
    assert result is not None
    assert result.kind == "write_path"
    assert "parent" in result.rule or "outside" in result.rule


@pytest.mark.asyncio
async def test_write_path_multiple_allowed():
    """Write to any of multiple allowed paths is OK."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_write_path(
        path="/tmp/test-output/result.json",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowed_paths=["/workspace/project", "/tmp/test-output"],
    )
    assert result is None  # No violation


# ═══════════════════════════════════════════════════════════
# Network access validation tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_network_exact_match_allowed():
    """Exact domain match in allowlist passes."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_network_access(
        domain="pypi.org",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowlist=["pypi.org", "*.github.com"],
    )
    assert result is None  # No violation


@pytest.mark.asyncio
async def test_network_wildcard_match():
    """Wildcard *.github.com matches api.github.com."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_network_access(
        domain="api.github.com",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowlist=["*.github.com"],
    )
    assert result is None  # No violation


@pytest.mark.asyncio
async def test_network_not_in_allowlist_blocked():
    """Domain not in allowlist is blocked."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_network_access(
        domain="random.evil.com",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowlist=["pypi.org", "*.github.com"],
    )
    assert result is not None
    assert result.kind == "network"
    assert result.action == "blocked"


# ═══════════════════════════════════════════════════════════
# Bash command validation tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bash_rm_rf_git_blocked():
    """rm -rf .git is caught by denied patterns."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_bash_command(
        command="rm -rf .git",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
    )
    assert result is not None
    assert result.kind == "denied_bash"


@pytest.mark.asyncio
async def test_bash_drop_table_blocked():
    """SQL injection pattern DROP TABLE is caught."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_bash_command(
        command='psql -c "DROP TABLE users"',
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
    )
    assert result is not None
    assert result.kind == "denied_bash"


@pytest.mark.asyncio
async def test_bash_safe_command_allowed():
    """A normal command like 'python test.py' is allowed."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db)
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_bash_command(
        command="python test.py",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
    )
    assert result is None  # No violation


# ═══════════════════════════════════════════════════════════
# Mode tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_strict_mode_blocks():
    """In strict mode, violations are 'blocked'."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db, mode="strict")
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_write_path(
        path="/etc/shadow",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowed_paths=["/workspace"],
    )
    assert result is not None
    assert result.action == "blocked"


@pytest.mark.asyncio
async def test_permissive_mode_logs_only():
    """In permissive mode, violations are 'logged' (not blocked)."""
    db = AsyncMock()
    enforcer = SecurityEnforcer(db, mode="permissive")
    agent_id = uuid.uuid4()
    team_id = uuid.uuid4()

    result = await enforcer.validate_write_path(
        path="/etc/shadow",
        agent_id=agent_id,
        team_id=team_id,
        task_id=None,
        allowed_paths=["/workspace"],
    )
    assert result is not None
    assert result.action == "logged"


# ═══════════════════════════════════════════════════════════
# Violation persistence tests
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_violation_persisted_to_db():
    """record_violation() creates a SecurityAudit row in the DB."""
    db = AsyncMock()
    db.add = MagicMock()

    enforcer = SecurityEnforcer(db)
    violation = SecurityViolation(
        kind="write_path",
        agent_id=uuid.uuid4(),
        team_id=uuid.uuid4(),
        run_task_id=10,
        detail="/etc/passwd",
        rule="outside_allowed_paths",
        action="blocked",
    )

    await enforcer.record_violation(violation)

    # Should have called db.add with a SecurityAudit instance
    db.add.assert_called_once()
    audit_row = db.add.call_args[0][0]
    assert audit_row.kind == "write_path"
    assert audit_row.detail == "/etc/passwd"
    assert audit_row.action == "blocked"
    db.commit.assert_awaited_once()
