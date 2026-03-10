"""Test fixtures — isolated DB sessions that rollback after each test.

Learn: Testing pattern for async SQLAlchemy + FastAPI + asyncpg:

1. Each test gets its own engine + connection + transaction (function-scoped)
2. The session uses join_transaction_mode="create_savepoint" so that
   when the service layer calls commit(), it creates a SAVEPOINT, not a real commit.
3. After the test, we rollback the outer transaction — all test data vanishes.

This gives us fast, isolated tests without any cross-test pollution.
"""

import pytest
import pytest_asyncio


# ─── E2E test support ─────────────────────────────────────


def pytest_addoption(parser):
    """Add --run-e2e flag for live agent tests."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run live E2E tests (requires running server + agent CLI)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests marked @pytest.mark.e2e unless --run-e2e is passed."""
    if config.getoption("--run-e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="Need --run-e2e to run")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from openclaw.config import settings
from openclaw.db.engine import get_db
from openclaw.main import app


TEST_DB_URL = settings.database_url


@pytest_asyncio.fixture()
async def db_session():
    """Per-test session with automatic rollback via savepoints.

    Creates a fresh engine+connection+transaction per test.
    join_transaction_mode="create_savepoint" means every session.commit()
    becomes a SAVEPOINT. After the test, the outer transaction rolls back.
    """
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(db_session):
    """HTTP client with the app's get_db and auth overridden for testing.

    Learn: We override get_current_user to return a mock identity so all
    protected routes work without real JWT tokens. This means tests don't
    need to register+login before each test case.
    """
    from openclaw.auth.dependencies import CurrentIdentity, get_current_user

    async def override_get_db():
        yield db_session

    def override_get_current_user():
        return CurrentIdentity(
            user_id="00000000-0000-0000-0000-000000000001",
            org_id="00000000-0000-0000-0000-000000000002",
            scopes=["all"],
            identity_type="user",
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def unauthenticated_client(db_session):
    """HTTP client WITHOUT auth override — for testing real JWT/API-key flows.

    Learn: The regular `client` fixture overrides get_current_user so that
    all protected routes pass. But auth tests (e.g. test_me_with_token)
    need the real auth run to validate real tokens. This fixture
    only overrides get_db (for DB isolation) and leaves auth untouched.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def raw_db():
    """Raw DB session for schema inspection (no savepoint wrapping).

    Learn: Some tests need to inspect DB schema objects (triggers, functions)
    which aren't affected by savepoints. This gives a direct connection.
    """
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.connect() as conn:
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
    await engine.dispose()
