"""FastAPI application factory.

Learn: App factory pattern — create_app() returns a configured FastAPI
instance. Lifespan manages startup/shutdown (database, Redis, etc.).
Middleware, CORS, and routers all registered here.

Unlike Delegate's 3400-line web.py monolith, this stays clean —
each concern lives in its own module.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openclaw import __version__
from openclaw.api import api_router
from openclaw.config import settings
from openclaw.observability.tracing import StructuredJsonFormatter

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle.

    Learn: FastAPI lifespan replaces on_event("startup") / on_event("shutdown").
    Anything before `yield` runs at startup, after `yield` runs at shutdown.
    """
    # ── Set up structured JSON logging ───────────────────────
    if settings.structured_logging:
        json_handler = logging.FileHandler(settings.log_file_json)
        json_handler.setFormatter(StructuredJsonFormatter())
        root_logger = logging.getLogger("openclaw")
        root_logger.addHandler(json_handler)
        root_logger.setLevel(logging.INFO)

    logger.info(
        "openclaw.starting",
        version=__version__,
        environment=settings.environment,
        port=settings.port,
    )

    # Initialize Redis connection pool (Phase 5)
    from openclaw.realtime.pubsub import close_redis, init_redis
    try:
        await init_redis()
        logger.info("openclaw.redis_connected", url=settings.redis_url)
    except Exception as e:
        logger.warning("openclaw.redis_unavailable", error=str(e))
        # Redis is optional — app works without real-time features

    # Start merge worker (Phase 13)
    from openclaw.services.merge_worker import MergeWorker
    merge_worker = MergeWorker(poll_interval=5.0)
    merge_task = asyncio.create_task(merge_worker.run_loop())
    logger.info("openclaw.merge_worker_started")

    yield

    # Shutdown
    logger.info("openclaw.shutdown")

    # Stop merge worker
    merge_worker.stop()
    merge_task.cancel()
    try:
        await merge_task
    except asyncio.CancelledError:
        pass

    # Close Redis
    await close_redis()

    # Close database engine
    from openclaw.db.engine import engine
    await engine.dispose()


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="OpenClaw Platform",
        description="AI Developer Productivity Platform — management layer for OpenClaw agents",
        version=__version__,
        lifespan=lifespan,
    )

    # ── Middleware stack ──────────────────────────────────────
    # Note: Starlette middleware executes in reverse order of registration.
    # Request flow: RequestId → Tracing → Security → RateLimit → CORS → handler

    from openclaw.middleware.rate_limit import RateLimitMiddleware
    from openclaw.middleware.request_id import RequestIdMiddleware
    from openclaw.middleware.security import SecurityHeadersMiddleware
    from openclaw.middleware.tracing import TracingMiddleware

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(TracingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        default_rpm=settings.rate_limit_rpm,
        auth_rpm=settings.rate_limit_auth_rpm,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routes
    app.include_router(api_router)

    # Mount WebSocket route (Phase 5 — real-time events)
    from openclaw.realtime.websocket import router as ws_router
    app.include_router(ws_router)

    return app


# Default app instance (used by uvicorn: openclaw.main:app)
app = create_app()
