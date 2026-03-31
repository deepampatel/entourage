"""Execution loop — dispatches RunTasks in parallel, respecting dependencies.

Phase 3: Parallel execution with worktree isolation, atomic agent acquisition,
and event-driven dispatch. Tasks whose dependencies are satisfied are dispatched
concurrently, up to max_concurrent_run_tasks.

Key improvements over Phase 2:
- Git worktrees: Each task runs in an isolated checkout (no file conflicts)
- Atomic agent acquire: UPDATE ... WHERE status='idle' prevents double-dispatch
- Event-driven: Task completion triggers immediate re-dispatch (no polling delay)
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.agent.runner import AgentRunner
from openclaw.config import settings
from openclaw.db.models import Agent, Run, RunTask, Repository, SandboxRun
from openclaw.events.store import EventStore
from openclaw.events.types import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RESUMED,
    RUN_STATUS_CHANGED,
    RUN_TASK_COMPLETED,
    RUN_TASK_FAILED,
    RUN_TASK_RETRIED,
    RUN_TASK_STARTED,
    SANDBOX_PASSED,
    SANDBOX_FAILED,
)
from openclaw.observability.tracing import log_structured, new_span, new_trace
from openclaw.services.sandbox_manager import SandboxManager
from openclaw.services.security_enforcer import SecurityEnforcer
from openclaw.services.run_budget_service import (
    RunBudgetExceededError,
    RunBudgetService,
)
from openclaw.services.run_service import RunService
from openclaw.services.resource_monitor import ResourceMonitor
from openclaw.services.git_service import GitService

logger = logging.getLogger("openclaw.services.execution_loop")


class ExecutionLoop:
    """Dispatches RunTasks in parallel, respecting dependencies.

    Phase 3 upgrades:
    - Git worktree isolation: Each task runs in its own checkout
    - Atomic agent acquisition: DB-level compare-and-swap prevents double-dispatch
    - Event-driven wakeup: Task completions signal immediate re-dispatch
    - _find_ready_tasks() returns ALL ready tasks (not just one)
    - Running tasks tracked as asyncio.Task futures
    - ResourceMonitor gates dispatch on CPU/memory/disk
    """

    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            from openclaw.db.engine import async_session_factory
            session_factory = async_session_factory
        self._session_factory = session_factory
        self._resource_monitor = ResourceMonitor()
        self._sandbox_mgr = SandboxManager()
        # Event-driven wakeup: set when a task completes so the loop
        # can re-dispatch immediately instead of sleeping.
        self._wakeup = asyncio.Event()

    async def run(self, run_id: uuid.UUID) -> dict:
        """Main loop: dispatch ready tasks in parallel until done or failure.

        Returns dict with final status and summary.
        """
        # Start a new trace for this run execution
        trace = new_trace()
        new_span("run.execute")
        log_structured(
            logger, logging.INFO, "run.execution.started",
            run_id=str(run_id), trace_id=trace,
        )

        # Track running tasks: run_task_id → asyncio.Task
        running: dict[int, asyncio.Task] = {}

        try:
            while True:
                # Open a fresh session each iteration (no stale reads)
                async with self._session_factory() as db:
                    run = await db.get(Run, run_id)
                    if not run:
                        raise ValueError(f"Run {run_id} not found")

                    # Check if run is still in executing state
                    if run.status != "executing":
                        logger.info(
                            "Run %s is '%s', stopping loop",
                            run_id,
                            run.status,
                        )
                        # Cancel any running futures
                        await self._cancel_running(running)
                        return {
                            "run_id": str(run_id),
                            "status": run.status,
                            "reason": "Run no longer executing",
                        }

                    # Load all tasks
                    result = await db.execute(
                        select(RunTask)
                        .where(RunTask.run_id == run_id)
                        .order_by(RunTask.id)
                    )
                    tasks = list(result.scalars().all())

                    if not tasks:
                        logger.warning("Run %s has no tasks", run_id)
                        svc = RunService(db)
                        await svc.change_status(run_id, "failed")
                        return {
                            "run_id": str(run_id),
                            "status": "failed",
                            "reason": "No tasks in run",
                        }

                    team_id = run.team_id

                # ── Collect completed futures ──────────────────────────
                for tid in list(running.keys()):
                    fut = running[tid]
                    if fut.done():
                        try:
                            success = fut.result()
                        except Exception as e:
                            logger.exception(
                                "Run task %d raised exception", tid
                            )
                            success = False

                        await self._handle_task_completion(
                            run_id, tid, success, team_id
                        )
                        del running[tid]

                # ── Re-read task state after completions ───────────────
                async with self._session_factory() as db:
                    result = await db.execute(
                        select(RunTask)
                        .where(RunTask.run_id == run_id)
                        .order_by(RunTask.id)
                    )
                    tasks = list(result.scalars().all())

                    # Check if all tasks are done
                    all_done = all(t.status == "done" for t in tasks)
                    if all_done:
                        logger.info(
                            "All tasks done for run %s, transitioning to reviewing",
                            run_id,
                        )
                        svc = RunService(db)
                        await svc.change_status(run_id, "reviewing")
                        await self._publish_event(
                            team_id,
                            RUN_COMPLETED,
                            {
                                "run_id": str(run_id),
                                "task_count": len(tasks),
                            },
                        )
                        return {
                            "run_id": str(run_id),
                            "status": "reviewing",
                            "reason": "All tasks completed",
                        }

                    # Any failed tasks? Fail the run.
                    failed_tasks = [t for t in tasks if t.status == "failed"]
                    if failed_tasks:
                        logger.error(
                            "Run %s has %d failed tasks, marking run failed",
                            run_id,
                            len(failed_tasks),
                        )
                        # Cancel remaining running tasks
                        await self._cancel_running(running)

                        svc = RunService(db)
                        await svc.change_status(run_id, "failed")
                        await self._publish_event(
                            team_id,
                            RUN_FAILED,
                            {
                                "run_id": str(run_id),
                                "failed_tasks": [
                                    {"id": t.id, "title": t.title}
                                    for t in failed_tasks
                                ],
                            },
                        )
                        return {
                            "run_id": str(run_id),
                            "status": "failed",
                            "reason": f"Task(s) failed: {[t.title for t in failed_tasks]}",
                        }

                    # ── Resource gate ──────────────────────────────────
                    can_dispatch, reason = self._resource_monitor.can_dispatch()
                    if not can_dispatch:
                        logger.info(
                            "Resource gate closed: %s. Waiting %ds",
                            reason,
                            settings.task_polling_interval_seconds,
                        )
                        await asyncio.sleep(settings.task_polling_interval_seconds)
                        continue

                    # ── Find ready tasks + idle agents ─────────────────
                    slots = settings.max_concurrent_run_tasks - len(running)
                    if slots <= 0:
                        # Max concurrency reached, wait for completions
                        await asyncio.sleep(settings.task_polling_interval_seconds)
                        continue

                    ready = self._find_ready_tasks(tasks, slots)

                    if not ready and not running:
                        # No ready tasks and nothing running — deadlock
                        in_progress = [t for t in tasks if t.status == "in_progress"]
                        if not in_progress:
                            logger.warning(
                                "Run %s: no ready tasks and nothing running (deadlock?)",
                                run_id,
                            )
                            svc = RunService(db)
                            await svc.change_status(run_id, "failed")
                            return {
                                "run_id": str(run_id),
                                "status": "failed",
                                "reason": "Deadlock: no ready tasks available",
                            }

                    if not ready:
                        # Tasks running but none ready yet — wait for completions
                        await asyncio.sleep(settings.task_polling_interval_seconds)
                        continue

                    # ── Atomic agent acquisition ───────────────────
                    agents = await self._acquire_agents_atomic(
                        db, team_id, len(ready)
                    )

                    if not agents:
                        logger.info(
                            "No idle agents for run %s, waiting",
                            run_id,
                        )
                        self._wakeup.clear()
                        try:
                            await asyncio.wait_for(
                                self._wakeup.wait(),
                                timeout=settings.task_polling_interval_seconds,
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue

                    # ── Dispatch ready tasks in parallel ───────────────
                    # Create worktrees for each task if the run has a repo
                    run = await db.get(Run, run_id)
                    repo_id = run.repository_id if run else None
                    worktree_paths: dict[int, Optional[str]] = {}

                    for task, agent in zip(ready, agents):
                        task.status = "in_progress"
                        task.agent_id = agent.id
                        task.started_at = datetime.now(timezone.utc)

                        # Create git worktree for isolated file access
                        wt_path = None
                        if repo_id:
                            try:
                                git_svc = GitService(db)
                                wt_info = await git_svc.create_worktree(
                                    task.id, repo_id
                                )
                                wt_path = wt_info.path
                                logger.info(
                                    "Created worktree for task %d at %s",
                                    task.id, wt_path,
                                )
                            except Exception:
                                logger.warning(
                                    "Failed to create worktree for task %d, "
                                    "falling back to repo root",
                                    task.id,
                                    exc_info=True,
                                )
                        worktree_paths[task.id] = wt_path

                    await db.commit()

                    # Create asyncio tasks outside the DB session
                    for task, agent in zip(ready, agents):
                        agent_id_str = str(agent.id)
                        logger.info(
                            "Dispatching run task %d (%s) to agent %s%s",
                            task.id,
                            task.title,
                            agent_id_str,
                            f" [worktree: {worktree_paths.get(task.id)}]"
                            if worktree_paths.get(task.id) else "",
                        )

                        # Fire task started event
                        await self._record_task_started(
                            run_id, task.id, task.title, agent_id_str, team_id
                        )

                        # Launch async task
                        running[task.id] = asyncio.create_task(
                            self._run_task(
                                run_id=run_id,
                                run_task_id=task.id,
                                agent_id=agent_id_str,
                                team_id=str(team_id),
                                task_title=task.title,
                                task_description=task.description,
                                worktree_path=worktree_paths.get(task.id),
                            )
                        )

                # ── Check budget ────────────────────────────────────────
                try:
                    async with self._session_factory() as db:
                        budget_svc = RunBudgetService(db)
                        budget = await budget_svc.check_budget(run_id)
                        if not budget.get("within_budget", True):
                            logger.warning(
                                "Run %s exceeded budget, pausing",
                                run_id,
                            )
                            await self._cancel_running(running)
                            svc = RunService(db)
                            await svc.change_status(run_id, "paused")
                            return {
                                "run_id": str(run_id),
                                "status": "paused",
                                "reason": "Budget exceeded",
                            }
                except RunBudgetExceededError:
                    await self._cancel_running(running)
                    async with self._session_factory() as db:
                        svc = RunService(db)
                        await svc.change_status(run_id, "paused")
                    return {
                        "run_id": str(run_id),
                        "status": "paused",
                        "reason": "Budget exceeded",
                    }

                # Event-driven wait: sleep until wakeup signal OR timeout
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(
                        self._wakeup.wait(),
                        timeout=settings.task_polling_interval_seconds,
                    )
                    logger.debug("Run %s: woken by task completion event", run_id)
                except asyncio.TimeoutError:
                    pass  # Normal polling fallback

        except Exception as e:
            logger.exception(
                "Execution loop for run %s failed unexpectedly", run_id
            )
            await self._cancel_running(running)
            try:
                async with self._session_factory() as db:
                    svc = RunService(db)
                    await svc.change_status(run_id, "failed")
            except Exception:
                logger.exception("Failed to mark run as failed")

            return {
                "run_id": str(run_id),
                "status": "failed",
                "reason": str(e),
            }

    # ─── Resume ────────────────────────────────────────────────────

    async def resume(self, run_id: uuid.UUID) -> dict:
        """Resume a paused or crashed run from its last checkpoint.

        1. Read run and tasks from DB
        2. Reset any in_progress tasks → todo (they were interrupted)
        3. Transition run → executing
        4. Start the normal execution loop

        Returns the result of the resumed execution.
        """
        logger.info("Resuming run %s", run_id)

        async with self._session_factory() as db:
            run = await db.get(Run, run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")

            if run.status not in ("paused", "failed", "executing"):
                raise ValueError(
                    f"Cannot resume run in '{run.status}' status. "
                    f"Expected 'paused', 'failed', or 'executing'."
                )

            # Reset in_progress tasks to todo (they were interrupted)
            result = await db.execute(
                select(RunTask)
                .where(RunTask.run_id == run_id)
                .order_by(RunTask.id)
            )
            tasks = list(result.scalars().all())
            reset_count = 0

            for task in tasks:
                if task.status == "in_progress":
                    task.status = "todo"
                    task.agent_id = None
                    task.started_at = None
                    reset_count += 1

            # Transition to executing
            svc = RunService(db)
            if run.status != "executing":
                await svc.change_status(run_id, "executing")

            # Record resume event
            events = EventStore(db)
            await events.append(
                stream_id=f"run:{run_id}",
                event_type=RUN_RESUMED,
                data={
                    "run_id": str(run_id),
                    "reset_tasks": reset_count,
                    "total_tasks": len(tasks),
                    "done_tasks": len([t for t in tasks if t.status == "done"]),
                },
            )
            await db.commit()

            logger.info(
                "Run %s resumed: reset %d in_progress tasks to todo",
                run_id,
                reset_count,
            )

        # Run the normal execution loop
        return await self.run(run_id)

    # ─── Task discovery ────────────────────────────────────────────

    def _find_ready_tasks(
        self, tasks: list[RunTask], max_count: int = 1
    ) -> list[RunTask]:
        """Find up to max_count tasks with all dependencies satisfied.

        A task is ready when:
        - Its status is "todo"
        - All tasks in its dependencies list have status "done"

        When max_count=1, this is equivalent to the Phase 1 serial behavior.
        """
        done_indices = set()
        for i, t in enumerate(tasks):
            if t.status == "done":
                done_indices.add(i)

        ready: list[RunTask] = []
        for i, task in enumerate(tasks):
            if task.status != "todo":
                continue

            deps = task.dependencies or []
            all_deps_done = True
            for dep_idx in deps:
                if dep_idx < len(tasks):
                    if dep_idx not in done_indices:
                        all_deps_done = False
                        break
                else:
                    # Invalid dependency index — treat as unmet
                    all_deps_done = False
                    break

            if all_deps_done:
                ready.append(task)
                if len(ready) >= max_count:
                    break

        return ready

    def _find_ready_task(
        self, tasks: list[RunTask]
    ) -> Optional[RunTask]:
        """Find a single ready task (backward compat alias for Phase 1)."""
        ready = self._find_ready_tasks(tasks, max_count=1)
        return ready[0] if ready else None

    async def _find_idle_agents(
        self,
        db: AsyncSession,
        team_id: uuid.UUID,
        max_count: int = 1,
        role: str = "engineer",
    ) -> list[Agent]:
        """Find up to max_count idle agents with the matching role."""
        result = await db.execute(
            select(Agent)
            .where(
                Agent.team_id == team_id,
                Agent.role == role,
                Agent.status == "idle",
            )
            .limit(max_count)
        )
        return list(result.scalars().all())

    async def _acquire_agent_atomic(
        self,
        db: AsyncSession,
        team_id: uuid.UUID,
        role: str = "engineer",
    ) -> Optional[Agent]:
        """Atomically acquire a single idle agent via compare-and-swap.

        Uses UPDATE ... WHERE status='idle' ... LIMIT 1 RETURNING to
        prevent double-dispatch. If two tasks try to grab the same agent
        concurrently, only one succeeds — the other gets None.

        This is the Phase 3 replacement for _find_idle_agent().
        """
        # Use raw SQL for atomic CAS — SQLAlchemy ORM doesn't support
        # UPDATE ... LIMIT 1 RETURNING natively on PostgreSQL.
        result = await db.execute(
            text("""
                UPDATE agents
                SET status = 'working'
                WHERE id = (
                    SELECT id FROM agents
                    WHERE team_id = :team_id
                      AND role = :role
                      AND status = 'idle'
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
            """),
            {"team_id": str(team_id), "role": role},
        )
        row = result.fetchone()
        if not row:
            return None
        # Refresh the ORM object from DB
        agent = await db.get(Agent, uuid.UUID(str(row[0])))
        return agent

    async def _acquire_agents_atomic(
        self,
        db: AsyncSession,
        team_id: uuid.UUID,
        max_count: int = 1,
        role: str = "engineer",
    ) -> list[Agent]:
        """Atomically acquire up to max_count idle agents.

        Each agent is set to 'working' atomically — no race conditions.
        Uses FOR UPDATE SKIP LOCKED so concurrent acquires don't block.
        """
        result = await db.execute(
            text("""
                UPDATE agents
                SET status = 'working'
                WHERE id IN (
                    SELECT id FROM agents
                    WHERE team_id = :team_id
                      AND role = :role
                      AND status = 'idle'
                    ORDER BY id
                    LIMIT :max_count
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id
            """),
            {"team_id": str(team_id), "role": role, "max_count": max_count},
        )
        rows = result.fetchall()
        if not rows:
            return []
        agents = []
        for row in rows:
            agent = await db.get(Agent, uuid.UUID(str(row[0])))
            if agent:
                agents.append(agent)
        return agents

    async def _find_idle_agent(
        self,
        db: AsyncSession,
        team_id: uuid.UUID,
        role: str = "engineer",
    ) -> Optional[Agent]:
        """Find a single idle agent (backward compat alias)."""
        agents = await self._find_idle_agents(db, team_id, max_count=1, role=role)
        return agents[0] if agents else None

    # ─── Task execution ────────────────────────────────────────────

    async def _run_task(
        self,
        run_id: uuid.UUID,
        run_task_id: int,
        agent_id: str,
        team_id: str,
        task_title: str,
        task_description: str,
        worktree_path: Optional[str] = None,
    ) -> bool:
        """Dispatch a single run task via AgentRunner.

        Phase 3: Accepts worktree_path for isolated file access. Signals
        the wakeup event on completion so the loop re-dispatches immediately.

        Returns True on success, False on failure.
        """
        new_span("task.dispatch")
        log_structured(
            logger, logging.INFO, "task.dispatched",
            task_id=run_task_id, agent_id=agent_id,
            run_id=str(run_id), title=task_title,
            worktree=worktree_path or "(repo root)",
        )
        runner = AgentRunner(session_factory=self._session_factory)

        # Build sibling context for parallel awareness
        sibling_context = ""
        try:
            from openclaw.services.sibling_context import SiblingContextBuilder
            async with self._session_factory() as db:
                builder = SiblingContextBuilder(db)
                sibling_context = await builder.build_context(run_id, run_task_id)
        except Exception:
            logger.debug("Failed to build sibling context", exc_info=True)

        # Build prompt for the agent
        sibling_section = f"\n\n{sibling_context}" if sibling_context else ""
        worktree_section = (
            f"\n\nYou are working in an isolated git worktree at: {worktree_path}\n"
            f"Your changes will not affect other agents. Commit freely."
            if worktree_path else ""
        )
        prompt = (
            f"## Run Task: {task_title}\n\n"
            f"{task_description}\n\n"
            f"Complete this task. When done, commit your changes with a clear "
            f"commit message describing what was done."
            f"{worktree_section}"
            f"{sibling_section}"
        )

        try:
            result = await runner.run_agent(
                agent_id=agent_id,
                team_id=team_id,
                prompt_override=prompt,
                working_directory=worktree_path,
                run_task_id=run_task_id,
            )

            # Always store agent output in RunTask.result
            async with self._session_factory() as db:
                ptask = await db.get(RunTask, run_task_id)
                if ptask:
                    ptask.result = {
                        "stdout": result.get("stdout", ""),
                        "stderr": result.get("stderr", ""),
                        "exit_code": result.get("exit_code"),
                        "duration_seconds": result.get("duration_seconds"),
                        "worktree": worktree_path,
                    }
                    if result.get("error"):
                        ptask.error = result["error"]
                    await db.commit()

            success = not result.get("error") and result.get("exit_code", 1) == 0

            # Release agent back to idle
            await self._release_agent(agent_id)

            # Signal wakeup so loop re-dispatches immediately
            self._wakeup.set()

            return success

        except Exception as e:
            logger.exception(
                "Agent run failed for run task %d", run_task_id
            )
            async with self._session_factory() as db:
                ptask = await db.get(RunTask, run_task_id)
                if ptask:
                    ptask.error = str(e)
                    await db.commit()

            # Release agent even on failure
            await self._release_agent(agent_id)
            self._wakeup.set()

            return False

    async def _release_agent(self, agent_id: str) -> None:
        """Release an agent back to idle status after task completion."""
        try:
            async with self._session_factory() as db:
                await db.execute(
                    text("""
                        UPDATE agents SET status = 'idle'
                        WHERE id = :agent_id
                    """),
                    {"agent_id": agent_id},
                )
                await db.commit()
        except Exception:
            logger.warning(
                "Failed to release agent %s back to idle",
                agent_id,
                exc_info=True,
            )

    # ─── Task lifecycle helpers ────────────────────────────────────

    async def _record_task_started(
        self,
        run_id: uuid.UUID,
        task_id: int,
        task_title: str,
        agent_id: str,
        team_id: uuid.UUID,
    ) -> None:
        """Record task started event in EventStore and publish via Redis."""
        async with self._session_factory() as db:
            events = EventStore(db)
            await events.append(
                stream_id=f"run:{run_id}",
                event_type=RUN_TASK_STARTED,
                data={
                    "run_id": str(run_id),
                    "run_task_id": task_id,
                    "title": task_title,
                    "agent_id": agent_id,
                },
            )
            await db.commit()

        await self._publish_event(
            team_id,
            RUN_TASK_STARTED,
            {
                "run_id": str(run_id),
                "run_task_id": task_id,
                "title": task_title,
            },
        )

    async def _handle_task_completion(
        self,
        run_id: uuid.UUID,
        task_id: int,
        success: bool,
        team_id: uuid.UUID,
    ) -> None:
        """Update task status and emit events after task completion.

        On failure, retries up to max_task_retries before marking as failed.
        """
        async with self._session_factory() as db:
            ptask = await db.get(RunTask, task_id)
            if not ptask:
                logger.error("Run task %d not found for completion", task_id)
                return

            events = EventStore(db)

            if success:
                # Optionally run sandbox tests before marking done
                sandbox_passed = await self._run_sandbox_if_configured(
                    run_id, task_id, team_id
                )
                if sandbox_passed is False:
                    # Sandbox tests failed — retry the task
                    if ptask.retry_count < settings.max_task_retries:
                        ptask.retry_count += 1
                        ptask.status = "todo"
                        ptask.agent_id = None
                        ptask.started_at = None
                        ptask.error = "Sandbox tests failed"
                        event_type = RUN_TASK_RETRIED
                        logger.warning(
                            "Run task %d sandbox failed, retrying (attempt %d/%d)",
                            task_id,
                            ptask.retry_count,
                            settings.max_task_retries,
                        )
                    else:
                        ptask.status = "failed"
                        ptask.completed_at = datetime.now(timezone.utc)
                        ptask.error = "Sandbox tests failed after all retries"
                        event_type = RUN_TASK_FAILED
                        logger.error(
                            "Run task %d sandbox failed after %d retries",
                            task_id,
                            ptask.retry_count,
                        )
                else:
                    ptask.status = "done"
                    ptask.completed_at = datetime.now(timezone.utc)
                    event_type = RUN_TASK_COMPLETED
                    logger.info(
                        "Run task %d completed successfully", task_id
                    )
            elif ptask.retry_count < settings.max_task_retries:
                # Retry: reset to todo with incremented retry count
                ptask.retry_count += 1
                ptask.status = "todo"
                ptask.agent_id = None  # Re-assign on next dispatch
                ptask.started_at = None
                ptask.error = None
                event_type = RUN_TASK_RETRIED
                logger.warning(
                    "Run task %d failed, retrying (attempt %d/%d)",
                    task_id,
                    ptask.retry_count,
                    settings.max_task_retries,
                )
            else:
                ptask.status = "failed"
                ptask.completed_at = datetime.now(timezone.utc)
                event_type = RUN_TASK_FAILED
                logger.error(
                    "Run task %d failed after %d retries",
                    task_id,
                    ptask.retry_count,
                )

            await events.append(
                stream_id=f"run:{run_id}",
                event_type=event_type,
                data={
                    "run_id": str(run_id),
                    "run_task_id": task_id,
                    "title": ptask.title,
                    "retry_count": ptask.retry_count,
                },
            )
            await db.commit()

        await self._publish_event(
            team_id,
            event_type,
            {
                "run_id": str(run_id),
                "run_task_id": task_id,
            },
        )

    # ─── Sandbox integration ──────────────────────────────────────

    async def _run_sandbox_if_configured(
        self,
        run_id: uuid.UUID,
        task_id: int,
        team_id: uuid.UUID,
    ) -> bool | None:
        """Run sandbox tests after task completion if configured.

        Returns:
            True if tests passed, False if failed, None if sandbox not configured/available.
        """
        if not settings.sandbox_enabled:
            return None

        docker_available = await self._sandbox_mgr.check_docker()
        if not docker_available:
            logger.debug("Docker not available, skipping sandbox for task %d", task_id)
            return None

        async with self._session_factory() as db:
            run = await db.get(Run, run_id)
            if not run or not run.repository_id:
                return None

            repo = await db.get(Repository, run.repository_id)
            if not repo:
                return None

            test_cmd = repo.config.get("test_cmd") if repo.config else None
            if not test_cmd:
                return None

            worktree_path = repo.local_path
            image = repo.config.get(
                "sandbox_image", settings.sandbox_default_image
            )
            setup_cmd = repo.config.get("setup_cmd")

        logger.info(
            "Running sandbox tests for task %d: %s",
            task_id,
            test_cmd,
        )

        result = await self._sandbox_mgr.run_tests(
            worktree_path=worktree_path,
            test_cmd=test_cmd,
            image=image,
            setup_cmd=setup_cmd,
            timeout=settings.sandbox_timeout_seconds,
        )

        # Persist the sandbox run
        async with self._session_factory() as db:
            run = SandboxRun(
                sandbox_id=result.sandbox_id,
                run_id=run_id,
                run_task_id=task_id,
                team_id=team_id,
                test_cmd=test_cmd,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                passed=result.passed,
                duration_seconds=result.duration_seconds,
                image=image,
                started_at=result.started_at,
                ended_at=result.ended_at,
            )
            db.add(run)
            await db.commit()

        # Publish sandbox event
        event_type = SANDBOX_PASSED if result.passed else SANDBOX_FAILED
        await self._publish_event(
            team_id,
            event_type,
            {
                "run_id": str(run_id),
                "run_task_id": task_id,
                "sandbox_id": result.sandbox_id,
                "passed": result.passed,
                "duration_seconds": result.duration_seconds,
            },
        )

        return result.passed

    # ─── Cleanup ───────────────────────────────────────────────────

    async def _cancel_running(self, running: dict[int, asyncio.Task]) -> None:
        """Cancel all running asyncio tasks and wait for cleanup."""
        for tid, fut in running.items():
            if not fut.done():
                logger.info("Cancelling running run task %d", tid)
                fut.cancel()

        # Wait for cancellations to propagate
        if running:
            await asyncio.gather(
                *running.values(), return_exceptions=True
            )
            running.clear()

    # ─── Event publishing ──────────────────────────────────────────

    async def _publish_event(
        self,
        team_id: uuid.UUID,
        event_type: str,
        data: dict,
    ) -> None:
        """Publish event to Redis for real-time UI updates."""
        try:
            redis = aioredis.from_url(settings.redis_url)
            await redis.publish(
                f"openclaw:events:{team_id}",
                json.dumps({"type": event_type, **data}),
            )
            await redis.close()
        except Exception:
            logger.debug("Failed to publish to Redis", exc_info=True)
