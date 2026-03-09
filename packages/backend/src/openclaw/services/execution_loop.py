"""Execution loop — dispatches PipelineTasks serially, respecting dependencies.

Phase 1: Serial execution (one task at a time). Parallel dispatch is Phase 2.

Learn: The loop runs as an asyncio.create_task from the API layer (same pattern
as agent_runs.py). It creates its own DB sessions via async_session_factory
since it runs outside a FastAPI request context.
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
from openclaw.db.models import Agent, Pipeline, PipelineTask
from openclaw.events.store import EventStore
from openclaw.events.types import (
    PIPELINE_COMPLETED,
    PIPELINE_FAILED,
    PIPELINE_STATUS_CHANGED,
    PIPELINE_TASK_COMPLETED,
    PIPELINE_TASK_FAILED,
    PIPELINE_TASK_STARTED,
)
from openclaw.services.pipeline_budget_service import (
    PipelineBudgetExceededError,
    PipelineBudgetService,
)
from openclaw.services.pipeline_service import PipelineService

logger = logging.getLogger("openclaw.services.execution_loop")


class ExecutionLoop:
    """Dispatches PipelineTasks serially, respecting dependencies.

    Learn: The loop is stateless — each call to run() creates fresh DB
    sessions. This makes it safe to launch via asyncio.create_task().
    """

    async def run(self, pipeline_id: uuid.UUID) -> dict:
        """Main loop: dispatch ready tasks one at a time until done or failure.

        Returns dict with final status and summary.
        """
        logger.info("Starting execution loop for pipeline %s", pipeline_id)

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
                            pipeline.team_id,
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
                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "failed")
                        await self._publish_event(
                            pipeline.team_id,
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

                    # Find next ready task (deps satisfied, status=todo)
                    ready_task = self._find_ready_task(tasks)
                    if not ready_task:
                        # No ready tasks but not all done — blocked
                        logger.warning(
                            "Pipeline %s: no ready tasks but not all done (deadlock?)",
                            pipeline_id,
                        )
                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "failed")
                        return {
                            "pipeline_id": str(pipeline_id),
                            "status": "failed",
                            "reason": "Deadlock: no ready tasks available",
                        }

                    # Find an idle agent
                    agent = await self._find_idle_agent(
                        db, pipeline.team_id, ready_task.assigned_role
                    )
                    if not agent:
                        logger.warning(
                            "No idle %s agent for pipeline %s, waiting 30s",
                            ready_task.assigned_role,
                            pipeline_id,
                        )
                        await asyncio.sleep(30)
                        continue

                    # Mark task in progress
                    ready_task.status = "in_progress"
                    ready_task.agent_id = agent.id
                    ready_task.started_at = datetime.now(timezone.utc)
                    await db.commit()

                    task_id_to_run = ready_task.id
                    task_title = ready_task.title
                    task_desc = ready_task.description
                    agent_id_str = str(agent.id)
                    team_id = pipeline.team_id

                # Record task started event
                async with async_session_factory() as db:
                    events = EventStore(db)
                    await events.append(
                        stream_id=f"pipeline:{pipeline_id}",
                        event_type=PIPELINE_TASK_STARTED,
                        data={
                            "pipeline_id": str(pipeline_id),
                            "pipeline_task_id": task_id_to_run,
                            "title": task_title,
                            "agent_id": agent_id_str,
                        },
                    )
                    await db.commit()

                await self._publish_event(
                    team_id,
                    PIPELINE_TASK_STARTED,
                    {
                        "pipeline_id": str(pipeline_id),
                        "pipeline_task_id": task_id_to_run,
                        "title": task_title,
                    },
                )

                # Run the task via AgentRunner
                logger.info(
                    "Running pipeline task %d (%s) via agent %s",
                    task_id_to_run,
                    task_title,
                    agent_id_str,
                )

                success = await self._run_task(
                    pipeline_id=pipeline_id,
                    pipeline_task_id=task_id_to_run,
                    agent_id=agent_id_str,
                    team_id=str(team_id),
                    task_title=task_title,
                    task_description=task_desc,
                )

                # Update task status based on result
                async with async_session_factory() as db:
                    ptask = await db.get(PipelineTask, task_id_to_run)
                    events = EventStore(db)

                    if success:
                        ptask.status = "done"
                        ptask.completed_at = datetime.now(timezone.utc)
                        event_type = PIPELINE_TASK_COMPLETED
                        logger.info(
                            "Pipeline task %d completed successfully",
                            task_id_to_run,
                        )
                    else:
                        ptask.status = "failed"
                        ptask.completed_at = datetime.now(timezone.utc)
                        event_type = PIPELINE_TASK_FAILED
                        logger.error(
                            "Pipeline task %d failed", task_id_to_run
                        )

                    await events.append(
                        stream_id=f"pipeline:{pipeline_id}",
                        event_type=event_type,
                        data={
                            "pipeline_id": str(pipeline_id),
                            "pipeline_task_id": task_id_to_run,
                            "title": task_title,
                        },
                    )
                    await db.commit()

                await self._publish_event(
                    team_id,
                    event_type,
                    {
                        "pipeline_id": str(pipeline_id),
                        "pipeline_task_id": task_id_to_run,
                    },
                )

                # Check budget
                try:
                    async with async_session_factory() as db:
                        budget_svc = PipelineBudgetService(db)
                        budget = await budget_svc.check_budget(pipeline_id)
                        if not budget.get("within_budget", True):
                            logger.warning(
                                "Pipeline %s exceeded budget, pausing",
                                pipeline_id,
                            )
                            svc = PipelineService(db)
                            await svc.change_status(pipeline_id, "paused")
                            return {
                                "pipeline_id": str(pipeline_id),
                                "status": "paused",
                                "reason": "Budget exceeded",
                            }
                except PipelineBudgetExceededError:
                    async with async_session_factory() as db:
                        svc = PipelineService(db)
                        await svc.change_status(pipeline_id, "paused")
                    return {
                        "pipeline_id": str(pipeline_id),
                        "status": "paused",
                        "reason": "Budget exceeded",
                    }

        except Exception as e:
            logger.exception(
                "Execution loop for pipeline %s failed unexpectedly", pipeline_id
            )
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

    def _find_ready_task(self, tasks: list[PipelineTask]) -> Optional[PipelineTask]:
        """Find the next task with all dependencies satisfied.

        A task is ready when:
        - Its status is "todo"
        - All tasks in its dependencies list have status "done"
        """
        # Build a map of task index → status (tasks are 0-indexed by position)
        done_ids = {t.id for t in tasks if t.status == "done"}

        for task in tasks:
            if task.status != "todo":
                continue

            deps = task.dependencies or []
            # Dependencies reference task indices (0-based), which map to task IDs
            # since tasks are ordered by ID and were created sequentially.
            # But we need to be careful — deps reference the position in the
            # original task_graph, not the PipelineTask.id. The PipelineTask
            # rows were created in order, so we can map by index.
            all_deps_done = True
            for dep_idx in deps:
                if dep_idx < len(tasks):
                    dep_task = tasks[dep_idx]
                    if dep_task.status != "done":
                        all_deps_done = False
                        break
                else:
                    # Invalid dependency index — treat as unmet
                    all_deps_done = False
                    break

            if all_deps_done:
                return task

        return None

    async def _find_idle_agent(
        self,
        db: AsyncSession,
        team_id: uuid.UUID,
        role: str = "engineer",
    ) -> Optional[Agent]:
        """Find an idle agent with the matching role from the team."""
        result = await db.execute(
            select(Agent).where(
                Agent.team_id == team_id,
                Agent.role == role,
                Agent.status == "idle",
            )
        )
        return result.scalars().first()

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
