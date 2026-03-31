"""Tests for ReactionEngine — automated responses to system events."""

import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.reaction_engine import ReactionConfig, ReactionEngine


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _make_session_factory(db_session):
    @asynccontextmanager
    async def factory():
        yield db_session
    return factory


# ═══════════════════════════════════════════════════════════
# Tests — ReactionConfig
# ═══════════════════════════════════════════════════════════


class TestReactionConfig:
    """Test config parsing from team config."""

    def test_defaults(self):
        config = ReactionConfig()
        assert config.stuck_agent_threshold_minutes == 30
        assert config.max_auto_retries == 3
        assert config.enabled is True

    def test_from_empty_config(self):
        config = ReactionConfig.from_team_config({})
        assert config.stuck_agent_threshold_minutes == 30
        assert config.enabled is True

    def test_from_custom_config(self):
        config = ReactionConfig.from_team_config({
            "reactions": {
                "stuck_agent_threshold_minutes": 15,
                "max_auto_retries": 5,
                "enabled": False,
            }
        })
        assert config.stuck_agent_threshold_minutes == 15
        assert config.max_auto_retries == 5
        assert config.enabled is False


# ═══════════════════════════════════════════════════════════
# Tests — Deduplication
# ═══════════════════════════════════════════════════════════


class TestDeduplication:
    """Test the reaction dedup logic."""

    def test_first_fire_allowed(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        assert engine._should_fire("test_key", cooldown_seconds=60) is True

    def test_second_fire_within_cooldown_blocked(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        engine._should_fire("test_key", cooldown_seconds=60)
        assert engine._should_fire("test_key", cooldown_seconds=60) is False

    def test_different_keys_independent(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        engine._should_fire("key_a", cooldown_seconds=60)
        assert engine._should_fire("key_b", cooldown_seconds=60) is True


# ═══════════════════════════════════════════════════════════
# Tests — Global Pause
# ═══════════════════════════════════════════════════════════


class TestGlobalPause:
    """Test team-level pause mechanics."""

    def test_not_paused_by_default(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        assert engine._is_team_paused("team-1") is False

    def test_paused_after_activation(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        engine._global_pause["team-1"] = time.monotonic() + 300
        assert engine._is_team_paused("team-1") is True

    def test_pause_expires(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        # Set pause to already expired
        engine._global_pause["team-1"] = time.monotonic() - 1
        assert engine._is_team_paused("team-1") is False

    @patch("openclaw.services.reaction_engine.aioredis")
    async def test_activate_global_pause(self, mock_redis):
        """activate_global_pause should set the pause flag."""
        mock_factory = AsyncMock()

        # Create a mock session context manager
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def factory():
            yield mock_session

        engine = ReactionEngine(session_factory=factory)

        # Mock redis
        mock_client = AsyncMock()
        mock_redis.from_url.return_value = mock_client

        await engine.activate_global_pause("team-1", reason="rate_limit")

        assert engine._is_team_paused("team-1") is True


# ═══════════════════════════════════════════════════════════
# Tests — Stop
# ═══════════════════════════════════════════════════════════


class TestEngineLifecycle:
    """Test start/stop mechanics."""

    def test_stop_sets_flag(self):
        engine = ReactionEngine(session_factory=AsyncMock())
        engine._running = True
        engine.stop()
        assert engine._running is False
