"""Agent runner — spawns coding agents via adapters and manages lifecycle.

Learn: The runner bridges the dispatcher (which decides WHEN to run an agent)
with the adapters (which decide HOW to run the agent). It handles:
1. Looking up the agent's adapter preference from config
2. Starting a session (with budget check)
3. Building the prompt from task context
4. Running the adapter (subprocess)
5. Recording results + ending the session
6. Publishing events to Redis for real-time UI

The runner uses async_session_factory to create DB sessions outside FastAPI
(same pattern as the dispatcher and merge worker).
"""

import json
import logging
import os
import uuid as _uuid
from pathlib import Path
from typing import Optional

import redis.asyncio as aioredis

from openclaw.agent.adapters import AdapterConfig, get_adapter
from openclaw.config import settings
from openclaw.db.engine import async_session_factory
from openclaw.db.models import Agent, Task, Team
from openclaw.events.store import EventStore
from openclaw.events.types import (
    AGENT_RUN_COMPLETED,
    AGENT_RUN_FAILED,
    AGENT_RUN_STARTED,
    AGENT_RUN_TIMEOUT,
)
from openclaw.observability.tracing import log_structured, new_span
from openclaw.services.session_service import SessionService

logger = logging.getLogger("openclaw.agent.runner")


def _find_mcp_server_path() -> str:
    """Locate the MCP server entry point (dist/index.js).

    Learn: Searches relative to the backend package, looking for
    the sibling mcp-server package in the monorepo.
    """
    if settings.mcp_server_path:
        return settings.mcp_server_path

    # Navigate from backend/src/openclaw/agent/ to project root
    here = Path(__file__).resolve().parent
    candidates = [
        here / ".." / ".." / ".." / ".." / ".." / "mcp-server" / "dist" / "index.js",
        Path.cwd() / "packages" / "mcp-server" / "dist" / "index.js",
    ]

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return str(resolved)

    # Fallback — let the adapter fail with a clear error
    return "packages/mcp-server/dist/index.js"


class AgentRunner:
    """Runs an agent turn end-to-end via an adapter.

    Learn: The runner is stateless — it creates DB sessions per invocation.
    This makes it safe to use from both the dispatcher (separate process)
    and the API endpoint (FastAPI BackgroundTasks).
    """

    async def run_agent(
        self,
        agent_id: str,
        team_id: str,
        task_id: Optional[int] = None,
        prompt_override: Optional[str] = None,
        adapter_override: Optional[str] = None,
    ) -> dict:
        """Execute a full agent run cycle.

        Returns dict with: session_id, exit_code, duration_seconds, error
        """
        async with async_session_factory() as db:
            # ── Load agent ────────────────────────────────────
            agent = await db.get(Agent, _uuid.UUID(agent_id))
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # ── Load task (if given) ──────────────────────────
            task = None
            if task_id:
                task = await db.get(Task, task_id)
                if not task:
                    raise ValueError(f"Task {task_id} not found")

            # ── Resolve team_id from agent if not provided ────
            effective_team_id = team_id or str(agent.team_id)

            # ── Determine adapter ─────────────────────────────
            adapter_name = (
                adapter_override
                or agent.config.get("adapter", None)
                or settings.default_adapter
            )
            adapter = get_adapter(adapter_name)

            # ── Validate environment ──────────────────────────
            valid, msg = adapter.validate_environment()
            if not valid:
                logger.error(
                    "Adapter %s validation failed: %s", adapter_name, msg
                )
                raise RuntimeError(
                    f"Adapter '{adapter_name}' not available: {msg}"
                )

            # ── Start session (includes budget check) ─────────
            session_svc = SessionService(db)
            session = await session_svc.start_session(
                agent_id=_uuid.UUID(agent_id),
                task_id=task_id,
                model=agent.model,
            )

            # ── Record run started event ──────────────────────
            events = EventStore(db)
            await events.append(
                stream_id=f"agent:{agent_id}",
                event_type=AGENT_RUN_STARTED,
                data={
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "adapter": adapter_name,
                    "session_id": session.id,
                },
            )
            await db.commit()

        # ── Load team conventions ─────────────────────────────
        conventions = []
        async with async_session_factory() as db:
            team = await db.get(Team, _uuid.UUID(effective_team_id))
            if team and team.config:
                conventions = [
                    c for c in team.config.get("conventions", [])
                    if c.get("active", True)
                ]

        # ── Load context carryover from task metadata ──────────
        context_data = {}
        if task and task.task_metadata:
            context_data = task.task_metadata.get("context", {})

        # ── Build prompt ──────────────────────────────────────
        prompt = prompt_override or adapter.build_prompt(
            task_title=task.title if task else "General work",
            task_description=task.description if task else "",
            agent_id=agent_id,
            team_id=effective_team_id,
            task_id=task_id or 0,
            role=agent.role,
            conventions=conventions or None,
            context=context_data or None,
        )

        # ── Build adapter config ──────────────────────────────
        mcp_path = _find_mcp_server_path()
        api_url = f"http://localhost:{settings.port}"

        adapter_config = AdapterConfig(
            mcp_server_command=["node", mcp_path],
            working_directory=os.getcwd(),
            api_url=api_url,
            agent_id=agent_id,
            team_id=effective_team_id,
            task_id=task_id or 0,
            timeout_seconds=agent.config.get(
                "timeout_seconds", settings.agent_timeout_seconds
            ),
        )

        # ── Run the adapter ───────────────────────────────────
        try:
            new_span("agent.run")
            log_structured(
                logger, logging.INFO, "agent.run.started",
                agent_id=agent_id, adapter=adapter_name,
                task_id=task_id, timeout=adapter_config.timeout_seconds,
            )

            result = await adapter.run(prompt, adapter_config)

            # ── Record result ─────────────────────────────────
            error = result.error if not result.ok else None

            async with async_session_factory() as db:
                session_svc = SessionService(db)
                await session_svc.end_session(session.id, error=error)

                events = EventStore(db)
                event_type = (
                    AGENT_RUN_TIMEOUT
                    if "timed out" in (result.error or "")
                    else AGENT_RUN_COMPLETED
                    if result.ok
                    else AGENT_RUN_FAILED
                )
                await events.append(
                    stream_id=f"agent:{agent_id}",
                    event_type=event_type,
                    data={
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "session_id": session.id,
                        "exit_code": result.exit_code,
                        "duration_seconds": round(result.duration_seconds, 1),
                        "error": error,
                    },
                )
                await db.commit()

            # ── Publish to Redis for real-time UI ─────────────
            try:
                redis = aioredis.from_url(settings.redis_url)
                await redis.publish(
                    f"openclaw:events:{effective_team_id}",
                    json.dumps(
                        {
                            "type": event_type,
                            "agent_id": agent_id,
                            "task_id": task_id,
                            "session_id": session.id,
                            "duration_seconds": round(
                                result.duration_seconds, 1
                            ),
                            "exit_code": result.exit_code,
                        }
                    ),
                )
                await redis.close()
            except Exception:
                logger.debug("Failed to publish to Redis", exc_info=True)

            log_structured(
                logger, logging.INFO, "agent.run.completed",
                agent_id=agent_id, adapter=adapter_name,
                duration_seconds=round(result.duration_seconds, 1),
                exit_code=result.exit_code,
                success=result.ok,
            )

            return {
                "session_id": session.id,
                "exit_code": result.exit_code,
                "duration_seconds": round(result.duration_seconds, 1),
                "error": error,
                "adapter": adapter_name,
            }

        except Exception as e:
            # ── Handle unexpected errors ──────────────────────
            logger.exception("Agent %s run failed unexpectedly", agent_id)

            async with async_session_factory() as db:
                session_svc = SessionService(db)
                await session_svc.end_session(session.id, error=str(e))

                events = EventStore(db)
                await events.append(
                    stream_id=f"agent:{agent_id}",
                    event_type=AGENT_RUN_FAILED,
                    data={
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "session_id": session.id,
                        "error": str(e),
                    },
                )
                await db.commit()

            raise
