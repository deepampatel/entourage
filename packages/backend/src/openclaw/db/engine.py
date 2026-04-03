"""Async SQLAlchemy engine and session factory.

Learn: SQLAlchemy 2.0 async mode — create_async_engine for connection pooling,
AsyncSession for per-request database access, dependency injection via FastAPI.

Unlike Delegate's raw sqlite3.connect() calls scattered everywhere, we have
one engine with connection pooling and proper session lifecycle.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from openclaw.config import settings

# Connection pool sized for concurrent agents.
# pool_size = base connections kept open
# max_overflow = extra connections under load (total = pool_size + max_overflow)
# pool_pre_ping = verify connection is alive before checkout (prevents stale conn errors)
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=max(settings.max_concurrent_agents // 2, 10),  # 16 for 32 agents
    max_overflow=max(settings.max_concurrent_agents, 20),    # 32 overflow
    pool_pre_ping=True,
    pool_recycle=1800,  # Recycle connections after 30 min (prevents DB timeout)
)

# Session factory — each request gets its own session.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a session per request, auto-closes."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


# ─── Redis singleton ─────────────────────────────────────

_redis_client = None


async def get_redis():
    """Get or create a shared Redis client. Reuses connection across calls."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=False,
        )
    return _redis_client


async def close_redis():
    """Close the shared Redis client (call on app shutdown)."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
