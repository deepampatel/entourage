"""Reaction engine — automated responses to system events.

Polls for state changes every 30s and executes configured reactions:
- Stuck agents → notify human
- Failed tasks → retry or escalate
- Rate limits → global team pause
- CI failures → send context to agent

Inspired by ComposioHQ/agent-orchestrator's lifecycle manager.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.config import settings
from openclaw.db.models import Agent, Run, RunTask, Session, Team
from openclaw.events.store import EventStore
from openclaw.events.types import (
    RUN_FAILED,
    RUN_TASK_FAILED,
    RUN_TASK_RETRIED,
)

logger = logging.getLogger("openclaw.services.reaction_engine")


# New event types for the reaction engine
REACTION_FIRED = "reaction.fired"
REACTION_ESCALATED = "reaction.escalated"
AGENT_STUCK_DETECTED = "agent.stuck_detected"
GLOBAL_PAUSE_ACTIVATED = "global_pause.activated"
GLOBAL_PAUSE_LIFTED = "global_pause.lifted"


@dataclass
class ReactionConfig:
    """Per-team reaction configuration (from team.config['reactions'])."""
    stuck_agent_threshold_minutes: int = 30
    max_auto_retries: int = 3
    escalation_after_retries: int = 2
    cooldown_seconds: int = 300  # 5 min dedup window
    global_pause_duration_seconds: int = 300  # 5 min pause on rate limit
    enabled: bool = True

    @classmethod
    def from_team_config(cls, config: dict) -> "ReactionConfig":
        reactions = config.get("reactions", {})
        return cls(
            stuck_agent_threshold_minutes=reactions.get("stuck_agent_threshold_minutes", 30),
            max_auto_retries=reactions.get("max_auto_retries", 3),
            escalation_after_retries=reactions.get("escalation_after_retries", 2),
            cooldown_seconds=reactions.get("cooldown_seconds", 300),
            global_pause_duration_seconds=reactions.get("global_pause_duration_seconds", 300),
            enabled=reactions.get("enabled", True),
        )


class ReactionEngine:
    """Polls for system events and auto-executes reactions."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from openclaw.db.engine import async_session_factory
            session_factory = async_session_factory
        self._session_factory = session_factory
        self._running = False
        # Dedup: maps "reaction_key" → last_fired_at (monotonic time)
        self._fired: dict[str, float] = {}
        # Track global pause per team
        self._global_pause: dict[str, float] = {}  # team_id → pause_until (monotonic)

    async def run_loop(self, poll_interval: float = 30.0):
        """Main polling loop. Call as asyncio.create_task(engine.run_loop())."""
        self._running = True
        logger.info("Reaction engine started (poll_interval=%.0fs)", poll_interval)

        while self._running:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Reaction engine poll cycle failed")
            await asyncio.sleep(poll_interval)

        logger.info("Reaction engine stopped")

    def stop(self):
        self._running = False

    async def _poll_cycle(self):
        """One poll cycle: check all active teams for actionable events."""
        async with self._session_factory() as db:
            # Find teams with active runs
            result = await db.execute(
                select(Team.id, Team.config)
                .join(Run, Run.team_id == Team.id)
                .where(Run.status.in_(["executing", "reviewing"]))
                .distinct()
            )
            active_teams = result.all()

        for team_id, team_config in active_teams:
            config = ReactionConfig.from_team_config(team_config or {})
            if not config.enabled:
                continue

            # Check if team is globally paused
            if self._is_team_paused(str(team_id)):
                continue

            try:
                await self._check_stuck_agents(team_id, config)
                await self._check_failed_tasks(team_id, config)
                await self._check_failed_runs(team_id, config)
                await self._cleanup_expired_pauses()
            except Exception:
                logger.exception("Reaction check failed for team %s", team_id)

    # ─── Stuck agent detection ─────────────────────────────────

    async def _check_stuck_agents(self, team_id, config: ReactionConfig):
        """Detect agents stuck in 'working' state too long."""
        threshold = datetime.now(timezone.utc) - timedelta(
            minutes=config.stuck_agent_threshold_minutes
        )

        async with self._session_factory() as db:
            # Find agents that are 'working' with no recent session activity
            result = await db.execute(
                select(Agent)
                .where(
                    Agent.team_id == team_id,
                    Agent.status == "working",
                )
            )
            working_agents = list(result.scalars().all())

            for agent in working_agents:
                # Check if there's an active session that started recently
                session_result = await db.execute(
                    select(Session)
                    .where(
                        Session.agent_id == agent.id,
                        Session.ended_at.is_(None),
                        Session.started_at < threshold,
                    )
                    .limit(1)
                )
                stale_session = session_result.scalars().first()

                if stale_session:
                    reaction_key = f"stuck_agent:{agent.id}"
                    if self._should_fire(reaction_key, config.cooldown_seconds):
                        logger.warning(
                            "Stuck agent detected: %s (team=%s, session=%d)",
                            agent.id, team_id, stale_session.id,
                        )
                        await self._fire_reaction(
                            team_id=str(team_id),
                            reaction_type="stuck_agent",
                            entity_id=str(agent.id),
                            message=f"Agent {agent.name} has been working for >{config.stuck_agent_threshold_minutes}min without completing",
                            data={
                                "agent_id": str(agent.id),
                                "agent_name": agent.name,
                                "session_id": stale_session.id,
                                "started_at": stale_session.started_at.isoformat(),
                            },
                        )
                        # Reset the agent to idle (it's stuck)
                        agent.status = "idle"
                        stale_session.ended_at = datetime.now(timezone.utc)
                        stale_session.error = "Reset by reaction engine: agent stuck"
                        await db.commit()

    # ─── Failed task retry/escalation ──────────────────────────

    async def _check_failed_tasks(self, team_id, config: ReactionConfig):
        """Check for recently failed run tasks and retry or escalate."""
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)

        async with self._session_factory() as db:
            result = await db.execute(
                select(RunTask)
                .join(Run, RunTask.run_id == Run.id)
                .where(
                    Run.team_id == team_id,
                    Run.status == "executing",
                    RunTask.status == "failed",
                    RunTask.updated_at >= five_minutes_ago,
                )
            )
            failed_tasks = list(result.scalars().all())

            for task in failed_tasks:
                reaction_key = f"failed_task:{task.id}:{task.retry_count}"
                if not self._should_fire(reaction_key, config.cooldown_seconds):
                    continue

                if task.retry_count < config.max_auto_retries:
                    # Auto-retry
                    logger.info(
                        "Auto-retrying failed task %d (attempt %d/%d)",
                        task.id, task.retry_count + 1, config.max_auto_retries,
                    )
                    task.status = "todo"
                    task.retry_count += 1
                    task.error = None
                    task.agent_id = None
                    task.started_at = None
                    await db.commit()

                    await self._fire_reaction(
                        team_id=str(team_id),
                        reaction_type="auto_retry",
                        entity_id=str(task.id),
                        message=f"Auto-retrying task '{task.title}' (attempt {task.retry_count}/{config.max_auto_retries})",
                        data={"task_id": task.id, "retry_count": task.retry_count},
                    )
                elif task.retry_count >= config.escalation_after_retries:
                    # Escalate to human
                    await self._escalate_to_human(
                        team_id=str(team_id),
                        message=f"Task '{task.title}' failed after {task.retry_count} retries. Error: {task.error or 'unknown'}",
                        data={"task_id": task.id, "error": task.error},
                    )

    # ─── Failed run detection ──────────────────────────────────

    async def _check_failed_runs(self, team_id, config: ReactionConfig):
        """Detect recently failed runs and notify."""
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)

        async with self._session_factory() as db:
            result = await db.execute(
                select(Run)
                .where(
                    Run.team_id == team_id,
                    Run.status == "failed",
                    Run.updated_at >= five_minutes_ago,
                )
            )
            failed_runs = list(result.scalars().all())

            for run in failed_runs:
                reaction_key = f"failed_run:{run.id}"
                if not self._should_fire(reaction_key, config.cooldown_seconds):
                    continue

                await self._fire_reaction(
                    team_id=str(team_id),
                    reaction_type="run_failed",
                    entity_id=str(run.id),
                    message=f"Run '{run.title}' failed",
                    data={"run_id": str(run.id), "title": run.title},
                )

    # ─── Global rate limit pause ───────────────────────────────

    async def activate_global_pause(self, team_id: str, reason: str = "rate_limit"):
        """Pause all executing runs for a team. Called externally when rate limit detected."""
        pause_until = time.monotonic() + 300  # 5 min default
        self._global_pause[team_id] = pause_until

        logger.warning(
            "Global pause activated for team %s (reason=%s, duration=300s)",
            team_id, reason,
        )

        # Pause all executing runs
        async with self._session_factory() as db:
            await db.execute(
                update(Run)
                .where(Run.team_id == team_id, Run.status == "executing")
                .values(status="paused")
            )
            await db.commit()

        await self._fire_reaction(
            team_id=team_id,
            reaction_type="global_pause",
            entity_id=team_id,
            message=f"Global pause activated: {reason}. All runs paused for 5 minutes.",
            data={"reason": reason, "duration_seconds": 300},
        )

    def _is_team_paused(self, team_id: str) -> bool:
        pause_until = self._global_pause.get(team_id, 0)
        if time.monotonic() < pause_until:
            return True
        self._global_pause.pop(team_id, None)
        return False

    async def _cleanup_expired_pauses(self):
        """Resume runs whose global pause has expired."""
        now = time.monotonic()
        expired = [tid for tid, until in self._global_pause.items() if now >= until]
        for team_id in expired:
            del self._global_pause[team_id]
            logger.info("Global pause lifted for team %s", team_id)

            async with self._session_factory() as db:
                # Resume paused runs (only those paused by global pause)
                await db.execute(
                    update(Run)
                    .where(Run.team_id == team_id, Run.status == "paused")
                    .values(status="executing")
                )
                await db.commit()

            await self._fire_reaction(
                team_id=team_id,
                reaction_type="global_pause_lifted",
                entity_id=team_id,
                message="Global pause lifted. Runs resumed.",
                data={},
            )

    # ─── Deduplication ─────────────────────────────────────────

    def _should_fire(self, reaction_key: str, cooldown_seconds: int) -> bool:
        """Check if enough time has passed since last fire of this reaction."""
        last_fired = self._fired.get(reaction_key, 0)
        now = time.monotonic()
        if now - last_fired < cooldown_seconds:
            return False
        self._fired[reaction_key] = now
        return True

    # ─── Fire reaction ─────────────────────────────────────────

    async def _fire_reaction(
        self,
        team_id: str,
        reaction_type: str,
        entity_id: str,
        message: str,
        data: dict,
    ):
        """Record a reaction event and publish to Redis."""
        # Record in event store
        async with self._session_factory() as db:
            events = EventStore(db)
            await events.append(
                stream_id=f"team:{team_id}",
                event_type=REACTION_FIRED,
                data={
                    "reaction_type": reaction_type,
                    "entity_id": entity_id,
                    "message": message,
                    **data,
                },
            )
            await db.commit()

        # Publish to Redis for real-time UI
        try:
            redis = aioredis.from_url(settings.redis_url)
            await redis.publish(
                f"openclaw:events:{team_id}",
                json.dumps({
                    "type": REACTION_FIRED,
                    "reaction_type": reaction_type,
                    "entity_id": entity_id,
                    "message": message,
                    **data,
                }),
            )
            await redis.close()
        except Exception:
            logger.debug("Failed to publish reaction to Redis", exc_info=True)

    async def _escalate_to_human(self, team_id: str, message: str, data: dict):
        """Create a human request for escalation."""
        from openclaw.db.models import HumanRequest

        async with self._session_factory() as db:
            # Find any agent in the team for the request
            result = await db.execute(
                select(Agent).where(Agent.team_id == team_id).limit(1)
            )
            agent = result.scalars().first()
            if not agent:
                return

            request = HumanRequest(
                team_id=team_id,
                agent_id=agent.id,
                kind="approval",
                question=f"[Escalation] {message}",
                options=["acknowledge", "retry", "cancel"],
                status="pending",
                timeout_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            db.add(request)

            events = EventStore(db)
            await events.append(
                stream_id=f"team:{team_id}",
                event_type=REACTION_ESCALATED,
                data={
                    "message": message,
                    "human_request_id": request.id,
                    **data,
                },
            )
            await db.commit()

        logger.info("Escalated to human: %s (team=%s)", message, team_id)

        # Publish notification
        try:
            redis = aioredis.from_url(settings.redis_url)
            await redis.publish(
                f"openclaw:events:{team_id}",
                json.dumps({
                    "type": REACTION_ESCALATED,
                    "message": message,
                    **data,
                }),
            )
            await redis.close()
        except Exception:
            pass
