"""Execution loop — dispatches PipelineTasks in parallel, respecting dependencies.

Phase 2: Parallel execution with resource monitoring. Tasks whose dependencies
are satisfied are dispatched concurrently, up to max_concurrent_pipeline_tasks.

Learn: The loop tracks running tasks as asyncio.Task futures in a dict. Each
iteration collects completed futures, dispatches new ready tasks, and sleeps.
When max_concurrent_pipeline_tasks=1, serial behavior is preserved (backward
compatible with Phase 1).
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.agent.runner import AgentRunner
from openclaw.config import settings
from openclaw.db.engine import async_session_factory
from openclaw.db.models import Agent, Pipeline, PipelineTask, Repository, SandboxRun
from openclaw.events.store import EventStore
from openclaw.events.types import (
    PIPELINE_COMPLETED,
    PIPELINE_FAILED,
    PIPELINE_RESUMED,
    PIPELINE_STATUS_CHANGED,
    PIPELINE_TASK_COMPLETED,
    PIPELINE_TASK_FAILED,
    PIPELINE_TASK_RETRIED,
    PIPELINE_TASK_STARTED,
    SANDBOX_PASSED,
    SANDBOX_FAILED,
)
from openclaw.services.sandbox_manager import SandboxManager
from openclaw.services.pipeline_budget_service import (
    PipelineBudgetExceededError,
    PipelineBudgetService,
)
from openclaw.services.pipeline_service import PipelineService
from openclaw.services.resource_monitor import ResourceMonitor

logger = logging.getLogger("openclaw.services.execution_loop")


class ExecutionLoop:
    """Dispatches PipelineTasks in parallel, respecting dependencies.

    Learn: The loop is stateless — each call to run() creates fresh DB
    sessions. This makes it safe to launch via asyncio.create_task().

    Key upgrade from Phase 1:
    - _find_ready_tasks() returns ALL ready tasks (not just one)
    - _find_idle_agents() returns multiple agents
    - Running tasks tracked as asyncio.Task futures
    - ResourceMonitor gates dispatch on CPU/memory/disk
    """

    def __init__(self) -> None:
        self._resource_monitor = ResourceMonitor()
        self._sandbox_mgr = SandboxManager()

    async def run(self, pipeline_id: uuid.UUID) -> dict:
        """Main loop: dispatch ready tasks in parallel until done or failure.

        Returns dict with final status and summary.
        """
        logger.info("Starting execution loop for pipeline %s", pipeline_id)

        # Track running tasks: pipeline_task_id → asyncio.Task
        running: dict[int, asyncio.Task] = {}

        try:
            while True:
                # Open a fresh session each iteration (no stale reads)
                async with async_session_factory() as db:
                    pipeline = await db.get(Pipeline, pipeline_id)
                    if not pipeline:
                        raise ValueError(f"Pipeline {pipeline_id} not found")

                    # Check if pipeline is still in executing state
                    if pipeline.status != "executing":
                        logger.info(
                            "Pipeline %s is '%s', stopping loop",
                            pipeline_id,
                            pipeline.status,
                        )
                        # Cancel any running futures
                        await self._cancel_running(running)
                        return {
                            "pipeline_id": str(pipeline_id),
                            "status": pipeline.status,
                            "reason": "Pipeline no longer executing",
                        }

                    # Load all tasks
                    result = await db.execute(
                        select(PipelineTask)
                        .where(PipelineTask.pipeline_id == pipeline_id)
                        .order_by(PipelineTask.id)
                    )
                    tasks = list(result.scalars().all())

                    if not tasks:
                        logger.warning("Pipeline %s has no tasks", pipeline_id)
                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "failed")
                        return {
                            "pipeline_id": str(pipeline_id),
                            "status": "failed",
                            "reason": "No tasks in pipeline",
                        }

                    team_id = pipeline.team_id

                # ── Collect completed futures ──────────────────────────
                for tid in list(running.keys()):
                    fut = running[tid]
                    if fut.done():
                        try:
                            success = fut.result()
                        except Exception as e:
                            logger.exception(
                                "Pipeline task %d raised exception", tid
                            )
                            success = False

                        await self._handle_task_completion(
                            pipeline_id, tid, success, team_id
                        )
                        del running[tid]

                # ── Re-read task state after completions ───────────────
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(PipelineTask)
                        .where(PipelineTask.pipeline_id == pipeline_id)
                        .order_by(PipelineTask.id)
                    )
                    tasks = list(result.scalars().all())

                    # Check if all tasks are done
                    all_done = all(t.status == "done" for t in tasks)
                    if all_done:
                        logger.info(
                            "All tasks done for pipeline %s, transitioning to reviewing",
                            pipeline_id,
                        )
                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "reviewing")
                        await self._publish_event(
                            team_id,
                            PIPELINE_COMPLETED,
                            {
                                "pipeline_id": str(pipeline_id),
                                "task_count": len(tasks),
                            },
                        )
                        return {
                            "pipeline_id": str(pipeline_id),
                            "status": "reviewing",
                            "reason": "All tasks completed",
                        }

                    # Any failed tasks? Fail the pipeline.
                    failed_tasks = [t for t in tasks if t.status == "failed"]
                    if failed_tasks:
                        logger.error(
                            "Pipeline %s has %d failed tasks, marking pipeline failed",
                            pipeline_id,
                            len(failed_tasks),
                        )
                        # Cancel remaining running tasks
                        await self._cancel_running(running)

                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "failed")
                        await self._publish_event(
                            team_id,
                            PIPELINE_FAILED,
                            {
                                "pipeline_id": str(pipeline_id),
                                "failed_tasks": [
                                    {"id": t.id, "title": t.title}
                                    for t in failed_tasks
                                ],
                            },
                        )
                        return {
                            "pipeline_id": str(pipeline_id),
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
                    slots = settings.max_concurrent_pipeline_tasks - len(running)
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
                                "Pipeline %s: no ready tasks and nothing running (deadlock?)",
                                pipeline_id,
                            )
                            svc = PipelineService(db)
                            await svc.change_status(pipeline_id, "failed")
                            return {
                                "pipeline_id": str(pipeline_id),
                                "status": "failed",
                                "reason": "Deadlock: no ready tasks available",
                            }

                    if not ready:
                        # Tasks running but none ready yet — wait for completions
                        await asyncio.sleep(settings.task_polling_interval_seconds)
                        continue

                    agents = await self._find_idle_agents(
                        db, team_id, len(ready)
                    )

                    if not agents:
                        logger.info(
                            "No idle agents for pipeline %s, waiting %ds",
                            pipeline_id,
                            settings.task_polling_interval_seconds,
                        )
                        await asyncio.sleep(settings.task_polling_interval_seconds)
                        continue

                    # ── Dispatch ready tasks in parallel ───────────────
                    for task, agent in zip(ready, agents):
                        task.status = "in_progress"
                        task.agent_id = agent.id
                        task.started_at = datetime.now(timezone.utc)
                    await db.commit()

                    # Create asyncio tasks outside the DB session
                    for task, agent in zip(ready, agents):
                        agent_id_str = str(agent.id)
                        logger.info(
                            "Dispatching pipeline task %d (%s) to agent %s",
                            task.id,
                            task.title,
                            agent_id_str,
                        )

                        # Fire task started event
                        await self._record_task_started(
                            pipeline_id, task.id, task.title, agent_id_str, team_id
                        )

                        # Launch async task
                        running[task.id] = asyncio.create_task(
                            self._run_task(
                                pipeline_id=pipeline_id,
                                pipeline_task_id=task.id,
                                agent_id=agent_id_str,
                                team_id=str(team_id),
                                task_title=task.title,
                                task_description=task.description,
                            )
                        )

                # ── Check budget ────────────────────────────────────────
                try:
                    async with async_session_factory() as db:
                        budget_svc = PipelineBudgetService(db)
                        budget = await budget_svc.check_budget(pipeline_id)
                        if not budget.get("within_budget", True):
                            logger.warning(
                                "Pipeline %s exceeded budget, pausing",
                                pipeline_id,
                            )
                            await self._cancel_running(running)
                            svc = PipelineService(db)
                            await svc.change_status(pipeline_id, "paused")
                            return {
                                "pipeline_id": str(pipeline_id),
                                "status": "paused",
                                "reason": "Budget exceeded",
                            }
                except PipelineBudgetExceededError:
                    await self._cancel_running(running)
                    async with async_session_factory() as db:
                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "paused")
                    return {
                        "pipeline_id": str(pipeline_id),
                        "status": "paused",
                        "reason": "Budget exceeded",
                    }

                await asyncio.sleep(settings.task_polling_interval_seconds)

        except Exception as e:
            logger.exception(
                "Execution loop for pipeline %s failed unexpectedly", pipeline_id
            )
            await self._cancel_running(running)
            try:
                async with async_session_factory() as db:
                    svc = PipelineService(db)
                    await svc.change_status(pipeline_id, "failed")
            except Exception:
                logger.exception("Failed to mark pipeline as failed")

            return {
                "pipeline_id": str(pipeline_id),
                "status": "failed",
                "reason": str(e),
            }

    # ─── Resume ────────────────────────────────────────────────────

    async def resume(self, pipeline_id: uuid.UUID) -> dict:
        """Resume a paused or crashed pipeline from its last checkpoint.

        1. Read pipeline and tasks from DB
        2. Reset any in_progress tasks → todo (they were interrupted)
        3. Transition pipeline → executing
        4. Start the normal execution loop

        Returns the result of the resumed execution.
        """
        logger.info("Resuming pipeline %s", pipeline_id)

        async with async_session_factory() as db:
            pipeline = await db.get(Pipeline, pipeline_id)
            if not pipeline:
                raise ValueError(f"Pipeline {pipeline_id} not found")

            if pipeline.status not in ("paused", "failed", "executing"):
                raise ValueError(
                    f"Cannot resume pipeline in '{pipeline.status}' status. "
                    f"Expected 'paused', 'failed', or 'executing'."
                )

            # Reset in_progress tasks to todo (they were interrupted)
            result = await db.execute(
                select(PipelineTask)
                .where(PipelineTask.pipeline_id == pipeline_id)
                .order_by(PipelineTask.id)
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
            svc = PipelineService(db)
            if pipeline.status != "executing":
                await svc.change_status(pipeline_id, "executing")

            # Record resume event
            events = EventStore(db)
            await events.append(
                stream_id=f"pipeline:{pipeline_id}",
                event_type=PIPELINE_RESUMED,
                data={
                    "pipeline_id": str(pipeline_id),
                    "reset_tasks": reset_count,
                    "total_tasks": len(tasks),
                    "done_tasks": len([t for t in tasks if t.status == "done"]),
                },
            )
            await db.commit()

            logger.info(
                "Pipeline %s resumed: reset %d in_progress tasks to todo",
                pipeline_id,
                reset_count,
            )

        # Run the normal execution loop
        return await self.run(pipeline_id)

    # ─── Task discovery ────────────────────────────────────────────

    def _find_ready_tasks(
        self, tasks: list[PipelineTask], max_count: int = 1
    ) -> list[PipelineTask]:
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

        ready: list[PipelineTask] = []
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
        self, tasks: list[PipelineTask]
    ) -> Optional[PipelineTask]:
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
        pipeline_id: uuid.UUID,
        pipeline_task_id: int,
        agent_id: str,
        team_id: str,
        task_title: str,
        task_description: str,
    ) -> bool:
        """Dispatch a single pipeline task via AgentRunner.

        Returns True on success, False on failure.
        """
        runner = AgentRunner()

        # Build prompt for the agent
        prompt = (
            f"## Pipeline Task: {task_title}\n\n"
            f"{task_description}\n\n"
            f"Complete this task. When done, commit your changes with a clear "
            f"commit message describing what was done."
        )

        try:
            result = await runner.run_agent(
                agent_id=agent_id,
                team_id=team_id,
                prompt_override=prompt,
            )

            if result.get("error"):
                # Record the error on the pipeline task
                async with async_session_factory() as db:
                    ptask = await db.get(PipelineTask, pipeline_task_id)
                    if ptask:
                        ptask.error = result["error"]
                        await db.commit()
                return False

            return result.get("exit_code", 1) == 0

        except Exception as e:
            logger.exception(
                "Agent run failed for pipeline task %d", pipeline_task_id
            )
            async with async_session_factory() as db:
                ptask = await db.get(PipelineTask, pipeline_task_id)
                if ptask:
                    ptask.error = str(e)
                    await db.commit()
            return False

    # ─── Task lifecycle helpers ────────────────────────────────────

    async def _record_task_started(
        self,
        pipeline_id: uuid.UUID,
        task_id: int,
        task_title: str,
        agent_id: str,
        team_id: uuid.UUID,
    ) -> None:
        """Record task started event in EventStore and publish via Redis."""
        async with async_session_factory() as db:
            events = EventStore(db)
            await events.append(
                stream_id=f"pipeline:{pipeline_id}",
                event_type=PIPELINE_TASK_STARTED,
                data={
                    "pipeline_id": str(pipeline_id),
                    "pipeline_task_id": task_id,
                    "title": task_title,
                    "agent_id": agent_id,
                },
            )
            await db.commit()

        await self._publish_event(
            team_id,
            PIPELINE_TASK_STARTED,
            {
                "pipeline_id": str(pipeline_id),
                "pipeline_task_id": task_id,
                "title": task_title,
            },
        )

    async def _handle_task_completion(
        self,
        pipeline_id: uuid.UUID,
        task_id: int,
        success: bool,
        team_id: uuid.UUID,
    ) -> None:
        """Update task status and emit events after task completion.

        On failure, retries up to max_task_retries before marking as failed.
        """
        async with async_session_factory() as db:
            ptask = await db.get(PipelineTask, task_id)
            if not ptask:
                logger.error("Pipeline task %d not found for completion", task_id)
                return

            events = EventStore(db)

            if success:
                # Optionally run sandbox tests before marking done
                sandbox_passed = await self._run_sandbox_if_configured(
                    pipeline_id, task_id, team_id
                )
                if sandbox_passed is False:
                    # Sandbox tests failed — retry the task
                    if ptask.retry_count < settings.max_task_retries:
                        ptask.retry_count += 1
                        ptask.status = "todo"
                        ptask.agent_id = None
                        ptask.started_at = None
                        ptask.error = "Sandbox tests failed"
                        event_type = PIPELINE_TASK_RETRIED
                        logger.warning(
                            "Pipeline task %d sandbox failed, retrying (attempt %d/%d)",
                            task_id,
                            ptask.retry_count,
                            settings.max_task_retries,
                        )
                    else:
                        ptask.status = "failed"
                        ptask.completed_at = datetime.now(timezone.utc)
                        ptask.error = "Sandbox tests failed after all retries"
                        event_type = PIPELINE_TASK_FAILED
                        logger.error(
                            "Pipeline task %d sandbox failed after %d retries",
                            task_id,
                            ptask.retry_count,
                        )
                else:
                    ptask.status = "done"
                    ptask.completed_at = datetime.now(timezone.utc)
                    event_type = PIPELINE_TASK_COMPLETED
                    logger.info(
                        "Pipeline task %d completed successfully", task_id
                    )
            elif ptask.retry_count < settings.max_task_retries:
                # Retry: reset to todo with incremented retry count
                ptask.retry_count += 1
                ptask.status = "todo"
                ptask.agent_id = None  # Re-assign on next dispatch
                ptask.started_at = None
                ptask.error = None
                event_type = PIPELINE_TASK_RETRIED
                logger.warning(
                    "Pipeline task %d failed, retrying (attempt %d/%d)",
                    task_id,
                    ptask.retry_count,
                    settings.max_task_retries,
                )
            else:
                ptask.status = "failed"
                ptask.completed_at = datetime.now(timezone.utc)
                event_type = PIPELINE_TASK_FAILED
                logger.error(
                    "Pipeline task %d failed after %d retries",
                    task_id,
                    ptask.retry_count,
                )

            await events.append(
                stream_id=f"pipeline:{pipeline_id}",
                event_type=event_type,
                data={
                    "pipeline_id": str(pipeline_id),
                    "pipeline_task_id": task_id,
                    "title": ptask.title,
                    "retry_count": ptask.retry_count,
                },
            )
            await db.commit()

        await self._publish_event(
            team_id,
            event_type,
            {
                "pipeline_id": str(pipeline_id),
                "pipeline_task_id": task_id,
            },
        )

    # ─── Sandbox integration ──────────────────────────────────────

    async def _run_sandbox_if_configured(
        self,
        pipeline_id: uuid.UUID,
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

        async with async_session_factory() as db:
            pipeline = await db.get(Pipeline, pipeline_id)
            if not pipeline or not pipeline.repository_id:
                return None

            repo = await db.get(Repository, pipeline.repository_id)
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
        async with async_session_factory() as db:
            run = SandboxRun(
                sandbox_id=result.sandbox_id,
                pipeline_id=pipeline_id,
                pipeline_task_id=task_id,
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
                "pipeline_id": str(pipeline_id),
                "pipeline_task_id": task_id,
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
                logger.info("Cancelling running pipeline task %d", tid)
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
