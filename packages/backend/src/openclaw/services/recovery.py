"""Crash recovery — find and recover orphaned work after backend restart.

Runs once on startup. Scans for state inconsistencies left behind by crashes:
- Agents stuck in 'working' with no active subprocess
- RunTasks stuck in 'in_progress' with no active agent
- Sessions that never closed
- Runs stuck in 'executing' with stale tasks

Inspired by ComposioHQ/agent-orchestrator's recovery system.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import Agent, Run, RunTask, Session
from openclaw.events.store import EventStore

logger = logging.getLogger("openclaw.services.recovery")

# Event types for recovery
RECOVERY_STARTED = "recovery.started"
RECOVERY_COMPLETED = "recovery.completed"
RECOVERY_AGENT_RESET = "recovery.agent_reset"
RECOVERY_TASK_RESET = "recovery.task_reset"
RECOVERY_SESSION_CLOSED = "recovery.session_closed"
RECOVERY_RUN_FAILED = "recovery.run_failed"


@dataclass
class RecoveryReport:
    """Summary of a recovery run."""
    agents_reset: int = 0
    tasks_reset: int = 0
    sessions_closed: int = 0
    runs_failed: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def total_recovered(self) -> int:
        return self.agents_reset + self.tasks_reset + self.sessions_closed

    @property
    def had_orphans(self) -> bool:
        return self.total_recovered > 0 or self.runs_failed > 0


class RecoveryManager:
    """Scan and recover orphaned state on startup."""

    # Sessions older than this are considered stale
    STALE_SESSION_THRESHOLD = timedelta(hours=2)
    # Tasks in_progress longer than this are considered orphaned
    STALE_TASK_THRESHOLD = timedelta(hours=1)

    def __init__(self, session_factory=None):
        if session_factory is None:
            from openclaw.db.engine import async_session_factory
            session_factory = async_session_factory
        self._session_factory = session_factory

    async def run(self, dry_run: bool = False) -> RecoveryReport:
        """Execute full recovery scan and repair.

        Args:
            dry_run: If True, only report what would be recovered without making changes.
        """
        report = RecoveryReport(started_at=datetime.now(timezone.utc))
        prefix = "[DRY RUN] " if dry_run else ""

        logger.info("%sStarting crash recovery scan...", prefix)

        try:
            # Record recovery start event
            if not dry_run:
                async with self._session_factory() as db:
                    events = EventStore(db)
                    await events.append(
                        stream_id="system:recovery",
                        event_type=RECOVERY_STARTED,
                        data={"dry_run": dry_run},
                    )
                    await db.commit()

            # Run all recovery checks
            await self._recover_stale_sessions(report, dry_run)
            await self._recover_stuck_agents(report, dry_run)
            await self._recover_orphaned_tasks(report, dry_run)
            await self._recover_stuck_runs(report, dry_run)

        except Exception as e:
            report.errors.append(str(e))
            logger.exception("Recovery scan failed")

        report.completed_at = datetime.now(timezone.utc)

        # Log summary
        if report.had_orphans:
            logger.warning(
                "%sRecovery complete: %d agents reset, %d tasks reset, "
                "%d sessions closed, %d runs failed, %d errors",
                prefix,
                report.agents_reset,
                report.tasks_reset,
                report.sessions_closed,
                report.runs_failed,
                len(report.errors),
            )
        else:
            logger.info("%sRecovery scan: no orphaned state found", prefix)

        # Record completion event
        if not dry_run:
            try:
                async with self._session_factory() as db:
                    events = EventStore(db)
                    await events.append(
                        stream_id="system:recovery",
                        event_type=RECOVERY_COMPLETED,
                        data={
                            "agents_reset": report.agents_reset,
                            "tasks_reset": report.tasks_reset,
                            "sessions_closed": report.sessions_closed,
                            "runs_failed": report.runs_failed,
                            "errors": report.errors,
                            "had_orphans": report.had_orphans,
                        },
                    )
                    await db.commit()
            except Exception:
                logger.debug("Failed to record recovery completion event")

        return report

    # ─── Stale sessions ────────────────────────────────────────

    async def _recover_stale_sessions(
        self, report: RecoveryReport, dry_run: bool
    ):
        """Close sessions that were never properly ended."""
        threshold = datetime.now(timezone.utc) - self.STALE_SESSION_THRESHOLD

        async with self._session_factory() as db:
            result = await db.execute(
                select(Session).where(
                    Session.ended_at.is_(None),
                    Session.started_at < threshold,
                )
            )
            stale_sessions = list(result.scalars().all())

            if not stale_sessions:
                return

            logger.info(
                "Found %d stale sessions (started before %s)",
                len(stale_sessions),
                threshold.isoformat(),
            )

            if dry_run:
                report.sessions_closed = len(stale_sessions)
                return

            now = datetime.now(timezone.utc)
            events = EventStore(db)

            for session in stale_sessions:
                session.ended_at = now
                session.error = "Closed by recovery: backend restarted"
                report.sessions_closed += 1

                await events.append(
                    stream_id=f"agent:{session.agent_id}",
                    event_type=RECOVERY_SESSION_CLOSED,
                    data={
                        "session_id": session.id,
                        "agent_id": str(session.agent_id),
                        "started_at": session.started_at.isoformat(),
                    },
                )

            await db.commit()

    # ─── Stuck agents ──────────────────────────────────────────

    async def _recover_stuck_agents(
        self, report: RecoveryReport, dry_run: bool
    ):
        """Reset agents stuck in 'working' status."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(Agent).where(Agent.status == "working")
            )
            stuck_agents = list(result.scalars().all())

            if not stuck_agents:
                return

            logger.info("Found %d agents stuck in 'working' status", len(stuck_agents))

            if dry_run:
                report.agents_reset = len(stuck_agents)
                return

            events = EventStore(db)

            for agent in stuck_agents:
                agent.status = "idle"
                report.agents_reset += 1

                await events.append(
                    stream_id=f"agent:{agent.id}",
                    event_type=RECOVERY_AGENT_RESET,
                    data={
                        "agent_id": str(agent.id),
                        "agent_name": agent.name,
                        "previous_status": "working",
                    },
                )

            await db.commit()

    # ─── Orphaned run tasks ────────────────────────────────────

    async def _recover_orphaned_tasks(
        self, report: RecoveryReport, dry_run: bool
    ):
        """Reset RunTasks stuck in 'in_progress' with no active agent."""
        threshold = datetime.now(timezone.utc) - self.STALE_TASK_THRESHOLD

        async with self._session_factory() as db:
            result = await db.execute(
                select(RunTask).where(
                    RunTask.status == "in_progress",
                    RunTask.started_at < threshold,
                )
            )
            orphaned_tasks = list(result.scalars().all())

            if not orphaned_tasks:
                return

            logger.info(
                "Found %d orphaned run tasks in 'in_progress'",
                len(orphaned_tasks),
            )

            if dry_run:
                report.tasks_reset = len(orphaned_tasks)
                return

            events = EventStore(db)

            for task in orphaned_tasks:
                task.status = "todo"
                task.agent_id = None
                task.started_at = None
                task.error = "Reset by recovery: orphaned after backend restart"
                report.tasks_reset += 1

                await events.append(
                    stream_id=f"run:{task.run_id}",
                    event_type=RECOVERY_TASK_RESET,
                    data={
                        "run_task_id": task.id,
                        "run_id": str(task.run_id),
                        "title": task.title,
                        "previous_status": "in_progress",
                    },
                )

            await db.commit()

    # ─── Stuck runs ────────────────────────────────────────────

    async def _recover_stuck_runs(
        self, report: RecoveryReport, dry_run: bool
    ):
        """Mark runs as failed if all their tasks are failed/stuck."""
        async with self._session_factory() as db:
            result = await db.execute(
                select(Run).where(Run.status == "executing")
            )
            executing_runs = list(result.scalars().all())

            for run in executing_runs:
                tasks_result = await db.execute(
                    select(RunTask).where(RunTask.run_id == run.id)
                )
                tasks = list(tasks_result.scalars().all())

                if not tasks:
                    continue

                # Check if all tasks are either done or failed
                active = [t for t in tasks if t.status in ("todo", "in_progress", "blocked")]
                failed = [t for t in tasks if t.status == "failed"]
                done = [t for t in tasks if t.status == "done"]

                # If all tasks are done/failed and none active, the run should be resolved
                if not active and failed and not done:
                    # All tasks failed, mark run as failed
                    if dry_run:
                        report.runs_failed += 1
                        continue

                    run.status = "failed"
                    run.updated_at = datetime.now(timezone.utc)
                    report.runs_failed += 1

                    events = EventStore(db)
                    await events.append(
                        stream_id=f"run:{run.id}",
                        event_type=RECOVERY_RUN_FAILED,
                        data={
                            "run_id": str(run.id),
                            "title": run.title,
                            "failed_tasks": len(failed),
                            "reason": "All tasks failed; detected during recovery",
                        },
                    )

            if not dry_run:
                await db.commit()
