"""Detailed health check endpoint.

Learn: Extended health endpoint that provides deeper system diagnostics
including database connectivity, Redis status, active agent sessions, and uptime.
"""

import time
from fastapi import APIRouter
from sqlalchemy import text

from openclaw import __version__
from openclaw.db.engine import engine

router = APIRouter()

# Track server start time for uptime calculation
_server_start_time = time.time()


@router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with database, Redis, tmux sessions, and uptime."""
    checks = {
        "server": "ok",
        "version": __version__,
        "uptime_seconds": round(time.time() - _server_start_time, 2),
    }

    # Check Postgres — try a simple query
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        checks["database"] = {"status": "ok", "type": "postgresql"}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}

    # Check Redis — try ping
    try:
        from redis.asyncio import from_url
        from openclaw.config import settings

        r = from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)}

    # Check active tmux agent sessions
    try:
        from openclaw.agent.runtime.tmux import TmuxRuntime

        runtime = TmuxRuntime()
        sessions = await runtime.list_sessions()
        checks["tmux_sessions"] = {
            "status": "ok",
            "active_count": len(sessions),
            "sessions": sessions,
        }
    except Exception as e:
        checks["tmux_sessions"] = {"status": "error", "error": str(e)}

    # Overall health status
    component_statuses = []
    if isinstance(checks.get("database"), dict):
        component_statuses.append(checks["database"].get("status"))
    if isinstance(checks.get("redis"), dict):
        component_statuses.append(checks["redis"].get("status"))
    if isinstance(checks.get("tmux_sessions"), dict):
        component_statuses.append(checks["tmux_sessions"].get("status"))

    status = "healthy" if all(s == "ok" for s in component_statuses) else "degraded"

    return {"status": status, **checks}
