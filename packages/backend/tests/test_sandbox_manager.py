"""Tests for SandboxManager — Docker-based isolated test execution."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.sandbox_manager import SandboxManager, SandboxResult


# ─── SandboxResult dataclass ────────────────────────────────


def test_sandbox_result_dataclass():
    """SandboxResult correctly stores all fields."""
    now = datetime.now(timezone.utc)
    result = SandboxResult(
        sandbox_id="abc123def456",
        exit_code=0,
        stdout="3 tests passed",
        stderr="",
        duration_seconds=12.5,
        passed=True,
        started_at=now,
        ended_at=now,
    )
    assert result.sandbox_id == "abc123def456"
    assert result.exit_code == 0
    assert result.passed is True
    assert result.duration_seconds == 12.5
    assert result.stdout == "3 tests passed"


# ─── Docker availability ────────────────────────────────────


@pytest.mark.asyncio
async def test_check_docker_available():
    """check_docker returns True when Docker daemon is running."""
    mgr = SandboxManager()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await mgr.check_docker()

    assert result is True


@pytest.mark.asyncio
async def test_check_docker_not_available():
    """check_docker returns False when Docker is not installed."""
    mgr = SandboxManager()

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await mgr.check_docker()

    assert result is False


@pytest.mark.asyncio
async def test_check_docker_caches_result():
    """check_docker caches the result after the first call."""
    mgr = SandboxManager()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await mgr.check_docker()
        await mgr.check_docker()
        await mgr.check_docker()

    # Should only call docker info once
    assert mock_exec.call_count == 1


# ─── run_tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_tests_success():
    """run_tests returns SandboxResult with passed=True on exit code 0."""
    mgr = SandboxManager()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"OK\n", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await mgr.run_tests("/workspace", "pytest tests/")

    assert result.passed is True
    assert result.exit_code == 0
    assert "OK" in result.stdout
    assert result.duration_seconds > 0


@pytest.mark.asyncio
async def test_run_tests_failure():
    """run_tests returns SandboxResult with passed=False on non-zero exit."""
    mgr = SandboxManager()

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"FAILED\n"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await mgr.run_tests("/workspace", "pytest tests/")

    assert result.passed is False
    assert result.exit_code == 1
    assert "FAILED" in result.stderr


@pytest.mark.asyncio
async def test_run_tests_timeout():
    """run_tests handles timeout gracefully."""
    mgr = SandboxManager()

    async def timeout_communicate():
        raise asyncio.TimeoutError()

    mock_proc = MagicMock()
    mock_proc.communicate = timeout_communicate

    # Also mock the kill container call
    mock_kill_proc = MagicMock()
    mock_kill_proc.wait = AsyncMock()

    call_count = 0
    async def mock_create_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_proc
        return mock_kill_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
        result = await mgr.run_tests("/workspace", "pytest", timeout=5)

    assert result.passed is False
    assert result.exit_code == 124  # timeout exit code
    assert "timed out" in result.stderr.lower()


# ─── Docker command construction ─────────────────────────────


def test_docker_cmd_construction_basic():
    """_build_docker_cmd includes correct flags, volume mount, network none."""
    mgr = SandboxManager()
    cmd = mgr._build_docker_cmd(
        sandbox_id="abc123",
        worktree_path="/path/to/worktree",
        cmd="pytest tests/",
    )

    assert "docker" in cmd
    assert "run" in cmd
    assert "--rm" in cmd
    assert "--network" in cmd
    assert "none" in cmd
    assert "--memory" in cmd
    assert "512m" in cmd
    assert "/path/to/worktree:/workspace:ro" in " ".join(cmd)
    assert "openclaw-sandbox=true" in " ".join(cmd)
    # Last 3 elements: shell invocation with the test command
    assert cmd[-3] == "sh"
    assert cmd[-2] == "-c"
    assert cmd[-1] == "pytest tests/"


def test_docker_cmd_with_setup():
    """_build_docker_cmd chains setup_cmd with test_cmd."""
    mgr = SandboxManager()
    cmd = mgr._build_docker_cmd(
        sandbox_id="abc123",
        worktree_path="/workspace",
        cmd="pytest",
        setup_cmd="pip install -e .",
    )

    assert cmd[-1] == "pip install -e . && pytest"


def test_docker_cmd_with_env():
    """_build_docker_cmd passes environment variables."""
    mgr = SandboxManager()
    cmd = mgr._build_docker_cmd(
        sandbox_id="abc123",
        worktree_path="/workspace",
        cmd="pytest",
        env={"CI": "true", "LANG": "en_US.UTF-8"},
    )

    cmd_str = " ".join(cmd)
    assert "-e CI=true" in cmd_str
    assert "-e LANG=en_US.UTF-8" in cmd_str


def test_docker_cmd_custom_image():
    """_build_docker_cmd uses the specified image."""
    mgr = SandboxManager()
    cmd = mgr._build_docker_cmd(
        sandbox_id="abc123",
        worktree_path="/workspace",
        cmd="npm test",
        image="node:20-slim",
    )

    assert "node:20-slim" in cmd


# ─── cleanup_stale ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_stale():
    """cleanup_stale removes labeled containers."""
    mgr = SandboxManager()

    # Mock docker ps returning 2 container IDs
    ps_proc = MagicMock()
    ps_proc.communicate = AsyncMock(
        return_value=(b"abc123 2024-01-01\ndef456 2024-01-01\n", b"")
    )
    ps_proc.returncode = 0

    rm_proc = MagicMock()
    rm_proc.wait = AsyncMock()

    call_count = 0
    async def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ps_proc
        return rm_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        removed = await mgr.cleanup_stale()

    assert removed == 2


@pytest.mark.asyncio
async def test_sandbox_not_available_graceful():
    """When Docker is unavailable, check_docker returns False without crashing."""
    mgr = SandboxManager()

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await mgr.check_docker()

    assert result is False
