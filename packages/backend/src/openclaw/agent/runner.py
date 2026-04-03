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



from openclaw.agent.adapters import AdapterConfig, get_adapter
from openclaw.config import settings
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
    # here = .../packages/backend/src/openclaw/agent/
    # project root = 5 levels up
    project_root = (here / ".." / ".." / ".." / ".." / "..").resolve()

    candidates = [
        project_root / "mcp-server" / "dist" / "index.js",
        project_root / "packages" / "mcp-server" / "dist" / "index.js",
        Path.cwd() / "packages" / "mcp-server" / "dist" / "index.js",
    ]

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return str(resolved)

    # Fallback — let the adapter fail with a clear error
    return str(project_root / "packages" / "mcp-server" / "dist" / "index.js")


class AgentRunner:
    """Runs an agent turn end-to-end via an adapter.

    Learn: The runner is stateless — it creates DB sessions per invocation.
    This makes it safe to use from both the dispatcher (separate process)
    and the API endpoint (FastAPI BackgroundTasks).
    """

    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            from openclaw.db.engine import async_session_factory
            session_factory = async_session_factory
        self._session_factory = session_factory

    @staticmethod
    def _find_repo_root() -> str:
        """Find the git repo root, falling back to cwd.

        Agents should work from the repo root so they can access
        all packages (backend, frontend, mcp-server, etc.)
        """
        import subprocess
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return os.getcwd()

    async def run_agent(
        self,
        agent_id: str,
        team_id: str,
        task_id: Optional[int] = None,
        prompt_override: Optional[str] = None,
        adapter_override: Optional[str] = None,
        working_directory: Optional[str] = None,
        run_task_id: Optional[int] = None,
    ) -> dict:
        """Execute a full agent run cycle.

        Returns dict with: session_id, exit_code, duration_seconds, error
        """
        async with self._session_factory() as db:
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
        async with self._session_factory() as db:
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

        # Use run_task_id for unique session naming, fall back to task_id
        effective_task_id = run_task_id or task_id or 0

        adapter_config = AdapterConfig(
            mcp_server_command=["node", mcp_path],
            working_directory=working_directory or self._find_repo_root(),
            api_url=api_url,
            agent_id=agent_id,
            team_id=effective_team_id,
            task_id=effective_task_id,
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

            async with self._session_factory() as db:
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
                from openclaw.db.engine import get_redis
                redis = await get_redis()
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
            except Exception:
                logger.debug("Failed to publish to Redis", exc_info=True)

            # ── Check for rate limit errors → trigger global pause ──
            if result.error and any(
                phrase in (result.error + result.stderr).lower()
                for phrase in ("rate limit", "429", "too many requests", "overloaded")
            ):
                try:
                    from openclaw.services.reaction_engine import ReactionEngine
                    engine = ReactionEngine(session_factory=self._session_factory)
                    await engine.activate_global_pause(
                        effective_team_id,
                        reason=f"Rate limit detected in agent {agent_id}",
                    )
                except Exception:
                    logger.debug("Failed to activate global pause", exc_info=True)

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
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except Exception as e:
            # ── Handle unexpected errors ──────────────────────
            logger.exception("Agent %s run failed unexpectedly", agent_id)

            async with self._session_factory() as db:
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
