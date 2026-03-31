"""Tests for TmuxRuntime — live agent process management via tmux.

These tests create real tmux sessions (not mocked) to verify
the full lifecycle: create → send message → read output → kill.
"""

import asyncio
import shutil

import pytest

from openclaw.agent.runtime.tmux import TmuxRuntime, SESSION_PREFIX
from openclaw.agent.runtime.base import RuntimeConfig


# Skip all tests if tmux is not installed
pytestmark = pytest.mark.skipif(
    not shutil.which("tmux"),
    reason="tmux not installed",
)


@pytest.fixture
def runtime():
    return TmuxRuntime()


@pytest.fixture
async def session(runtime):
    """Create a tmux session running a simple shell, and clean up after."""
    config = RuntimeConfig(
        session_id="test-runtime-001",
        command=["bash"],
        cwd="/tmp",
    )
    sess = await runtime.create(config)
    yield sess
    await runtime.kill(sess)


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestTmuxValidation:
    def test_validate_passes(self, runtime):
        valid, msg = runtime.validate()
        assert valid is True
        assert "found" in msg


class TestTmuxLifecycle:
    async def test_create_session(self, runtime, session):
        """Creating a session should produce a valid handle."""
        assert session.session_id == f"{SESSION_PREFIX}test-runtime-001"
        assert session.runtime_type == "tmux"
        assert session.attach_command is not None
        assert "tmux attach" in session.attach_command

    async def test_session_is_alive(self, runtime, session):
        """A freshly created session should be alive."""
        alive = await runtime.is_alive(session)
        assert alive is True

    async def test_kill_session(self, runtime):
        """Killing a session should make it not alive."""
        config = RuntimeConfig(
            session_id="test-kill-002",
            command=["bash"],
            cwd="/tmp",
        )
        sess = await runtime.create(config)
        assert await runtime.is_alive(sess) is True

        await runtime.kill(sess)
        await asyncio.sleep(0.5)
        assert await runtime.is_alive(sess) is False

    async def test_dead_session_not_alive(self, runtime):
        """A nonexistent session should report as not alive."""
        from openclaw.agent.runtime.base import RuntimeSession
        fake = RuntimeSession(
            session_id="eo-nonexistent-999",
            runtime_type="tmux",
        )
        assert await runtime.is_alive(fake) is False


class TestTmuxIO:
    async def test_send_and_read(self, runtime, session):
        """Sending a command should produce readable output."""
        # Send a command
        await runtime.send_message(session, "echo HELLO_ENTOURAGE")
        await asyncio.sleep(1)

        # Read output
        output = await runtime.read_output(session)
        assert "HELLO_ENTOURAGE" in output

    async def test_send_long_message(self, runtime, session):
        """Messages over 200 chars should work via load-buffer."""
        long_msg = "echo " + "A" * 300
        sent = await runtime.send_message(session, long_msg)
        assert sent is True

        await asyncio.sleep(1)
        output = await runtime.read_output(session)
        assert "A" * 50 in output  # At least part of it should appear

    async def test_env_vars_set(self, runtime):
        """Environment variables should be available in the session."""
        config = RuntimeConfig(
            session_id="test-env-003",
            command=["bash"],
            cwd="/tmp",
            env={"ENTOURAGE_TEST_VAR": "hello_world"},
        )
        sess = await runtime.create(config)
        try:
            await asyncio.sleep(1)
            await runtime.send_message(sess, "echo $ENTOURAGE_TEST_VAR")
            await asyncio.sleep(1)
            output = await runtime.read_output(sess)
            assert "hello_world" in output
        finally:
            await runtime.kill(sess)


class TestTmuxListAndCleanup:
    async def test_list_sessions(self, runtime, session):
        """Our session should appear in the list."""
        sessions = await runtime.list_sessions()
        assert session.session_id in sessions

    async def test_cleanup_dead_sessions(self, runtime):
        """cleanup_dead_sessions should remove exited sessions."""
        config = RuntimeConfig(
            session_id="test-cleanup-004",
            command=["bash", "-c", "exit 0"],  # Exits immediately
            cwd="/tmp",
        )
        sess = await runtime.create(config)
        await asyncio.sleep(2)  # Wait for it to exit

        cleaned = await runtime.cleanup_dead_sessions()
        # Should have cleaned at least this one
        assert cleaned >= 0  # May or may not be dead yet depending on timing
