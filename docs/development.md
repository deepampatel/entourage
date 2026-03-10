# Development Guide — Entourage

## Prerequisites

- Docker Desktop (for Postgres + Redis)
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+

## Setup

### 1. Infrastructure

```bash
docker compose up -d
```

This starts:
- PostgreSQL 16 on port **5433** (not 5432, to avoid conflicts with local Postgres)
- Redis 7 on port **6379**

### 2. Backend

```bash
cd packages/backend
uv sync                       # install all dependencies
uv run alembic upgrade head   # create/update database tables
uv run uvicorn openclaw.main:app --reload --port 8000
```

The API is now at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### 3. MCP Server

```bash
cd packages/mcp-server
npm install
npm run build     # compile TypeScript → dist/
npm run dev       # watch mode for development
```

### 4. Frontend

```bash
cd packages/frontend
npm install
npm run dev       # Vite dev server at http://localhost:5173
```

The frontend proxies `/api` requests to the backend (configured in `vite.config.ts`).

## Configuration

All config is via environment variables with the `OPENCLAW_` prefix.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENCLAW_DATABASE_URL` | `postgresql+asyncpg://openclaw:openclaw_dev@localhost:5433/openclaw` | Database connection |
| `OPENCLAW_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `OPENCLAW_ANTHROPIC_API_KEY` | `""` | For built-in agent runner |
| `OPENCLAW_JWT_SECRET` | `change-me-in-production` | JWT signing key (min 32 bytes recommended) |
| `OPENCLAW_DEBUG` | `false` | Enable SQL echo logging |
| `OPENCLAW_ENVIRONMENT` | `development` | Environment name |
| `OPENCLAW_API_URL` | `http://localhost:8000` | MCP server → backend URL |

## Running Tests

```bash
cd packages/backend
uv run pytest tests/ -v        # all 395 tests, ~23s
uv run pytest tests/ -v -k auth   # run only auth tests
```

### Test Architecture

Tests use a **savepoint rollback** pattern for isolation:

1. Each test gets its own database connection + transaction
2. The session uses `join_transaction_mode="create_savepoint"` — when the service layer calls `commit()`, it creates a SAVEPOINT instead of a real commit
3. After the test, the outer transaction rolls back — all test data vanishes

This means:
- Tests run against the real database (not mocks)
- Tests are fully isolated — no data leaks between tests
- No cleanup needed — rollback handles everything
- Fast — 395 tests in ~23 seconds

### Test Structure

```
tests/
  conftest.py                      Fixtures: db_session (savepoint), client (HTTP), raw_db
  test_health.py                   Smoke test (1 test)
  test_teams_api.py                Phase 1: orgs, teams, agents, repos (17 tests)
  test_tasks_api.py                Phase 2: tasks, state machine, deps, messages (19 tests)
  test_git_api.py                  Phase 3: worktrees, diffs, file reading (14 tests)
  test_sessions_api.py             Phase 4: sessions, cost tracking, budgets (16 tests)
  test_human_requests_api.py       Phase 7: human-in-the-loop (15 tests)
  test_reviews_api.py              Phase 8: reviews, verdicts, merge (22 tests)
  test_dispatch_api.py             Phase 6: dispatch status, PG triggers (8 tests)
  test_auth_api.py                 Phase 9: register, login, JWT, API keys (16 tests)
  test_webhooks_settings_api.py    Phase 10: webhooks, settings (19 tests)
  test_run_service.py              Runs: CRUD, lifecycle, task graph (35 tests)
  test_planner_service.py          Planner: AI + template fallback (18 tests)
  test_execution_loop.py           Execution loop: dispatch, retry, budget (42 tests)
  test_run_resume.py            Run resume + recovery (12 tests)
  test_sandbox_integration.py      Sandbox: isolation, resource limits (15 tests)
  test_task_retry.py               Task retry: backoff, max attempts (11 tests)
  test_e2e_lifecycle.py            Full lifecycle integration test (1 test)
```

### Writing New Tests

```python
@pytest.mark.asyncio
async def test_something(client):
    """client fixture gives you an HTTP client with DB isolation."""
    # Create test data via the API
    resp = await client.post("/api/v1/orgs", json={"name": "Test", "slug": "test"})
    org = resp.json()

    # Assert
    assert resp.status_code == 201
    assert org["slug"] == "test"
```

For tests that need direct DB access:

```python
@pytest.mark.asyncio
async def test_with_db(client, db_session):
    """db_session gives you direct SQLAlchemy access."""
    from sqlalchemy import select
    from openclaw.db.models import Event

    # Do something via API...
    await client.post(...)

    # Query DB directly
    result = await db_session.execute(select(Event))
    events = list(result.scalars().all())
```

For tests that need to inspect schema-level objects (triggers, functions):

```python
@pytest.mark.asyncio
async def test_trigger_exists(raw_db):
    """raw_db fixture — bypasses savepoints for schema inspection."""
    from sqlalchemy import text
    result = await raw_db.execute(text(
        "SELECT tgname FROM pg_trigger WHERE tgname = 'trg_message_notify'"
    ))
    assert result.scalar() is not None
```

### Key Testing Gotcha: Async Lazy Loading

SQLAlchemy async does not support lazy loading of relationships. When returning ORM objects with relationships from async endpoints:

```python
# BAD — will raise MissingGreenlet when FastAPI serializes
review = await db.get(Review, review_id, options=[selectinload(Review.comments)])

# GOOD — fresh SELECT query forces eager loading
q = select(Review).where(Review.id == review_id).options(selectinload(Review.comments))
result = await db.execute(q)
review = result.scalars().first()
```

The `db.get()` with `selectinload` can return a cached identity map object without re-running the query. Always use a fresh `select()` when you need eagerly loaded relationships.

## Database Migrations

Migrations are auto-generated from model changes using Alembic.

```bash
cd packages/backend

# After changing models.py:
uv run alembic revision --autogenerate -m "description of change"

# For manual migrations (e.g., PG triggers):
uv run alembic revision -m "description of change"
# Then edit the generated file to add raw SQL

# Apply:
uv run alembic upgrade head

# Rollback one step:
uv run alembic downgrade -1

# Show current revision:
uv run alembic current
```

### Current Migrations

| Revision | Description |
|----------|-------------|
| `858c9f17a644` | Phase 1: orgs, teams, users, agents, repos, events, sessions |
| `0ac40d24a4c8` | Phase 2: tasks and messages |
| `31a70288aa72` | Phase 7: human_requests |
| `ba9513c684e2` | Phase 8: reviews, review_comments, merge_jobs |
| `85a67264382e` | Phase 6: PG LISTEN/NOTIFY triggers (manual) |
| `b9273a98ca4c` | Phase 9: api_keys |
| `8fd38d37a5f3` | Phase 10: webhooks, webhook_deliveries |
| `d29768ed705e` | Phase 10: teams.config column |

## Project Structure

```
openclaw/
├── docker-compose.yml                  Postgres 16 (port 5433) + Redis 7
├── pnpm-workspace.yaml                 Monorepo config
├── package.json                        Root package.json
│
├── packages/
│   ├── backend/                        Python — FastAPI
│   │   ├── pyproject.toml              Dependencies + pytest config
│   │   ├── alembic.ini                 Migration config
│   │   ├── uv.lock                     Lockfile (commit this)
│   │   ├── src/openclaw/
│   │   │   ├── __init__.py             Version string
│   │   │   ├── main.py                 App factory, lifespan, CORS
│   │   │   ├── config.py              pydantic-settings
│   │   │   ├── api/
│   │   │   │   ├── __init__.py         Router aggregation (11 routers)
│   │   │   │   ├── health.py           Health check (Postgres + Redis)
│   │   │   │   ├── teams.py            Org/Team/Agent/Repo CRUD
│   │   │   │   ├── tasks.py            Tasks + state machine + messages
│   │   │   │   ├── git.py              Worktrees, diffs, file reading
│   │   │   │   ├── sessions.py         Sessions, costs, budgets
│   │   │   │   ├── human_requests.py   Human-in-the-loop
│   │   │   │   ├── reviews.py          Code reviews + merge
│   │   │   │   ├── dispatch.py         Dispatch status
│   │   │   │   ├── auth.py             Register, login, JWT, API keys
│   │   │   │   ├── webhooks.py         Webhook CRUD + receiver
│   │   │   │   └── settings.py         Team/org settings
│   │   │   ├── auth/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── password.py         SHA-256 + salt password hashing
│   │   │   │   ├── jwt.py              JWT token create/verify
│   │   │   │   └── dependencies.py     FastAPI auth deps (JWT + API key)
│   │   │   ├── db/
│   │   │   │   ├── models.py           15 ORM models (source of truth)
│   │   │   │   ├── engine.py           Async engine + get_db dependency
│   │   │   │   └── migrations/         8 Alembic versions
│   │   │   ├── dispatcher/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── turn_dispatcher.py  PG LISTEN/NOTIFY dispatcher
│   │   │   │   └── main.py             CLI entry point
│   │   │   ├── services/
│   │   │   │   ├── team_service.py     Team logic + auto-provision
│   │   │   │   ├── task_service.py     State machine + DAG + messages
│   │   │   │   ├── session_service.py  Session + cost management
│   │   │   │   ├── human_loop.py       Human request lifecycle
│   │   │   │   ├── review_service.py   Reviews + merge jobs
│   │   │   │   ├── webhook_service.py  Webhook CRUD + event processing
│   │   │   │   ├── run_service.py Run CRUD + lifecycle
│   │   │   │   ├── planner_service.py  AI + template task planning
│   │   │   │   └── execution_loop.py   Run execution + dispatch
│   │   │   ├── events/
│   │   │   │   ├── store.py            Append-only EventStore
│   │   │   │   └── types.py            Event type constants (30+ types)
│   │   │   ├── agent/
│   │   │   │   ├── runner.py            AgentRunner (DI-ready)
│   │   │   │   └── adapters/            Claude Code, Codex, Aider
│   │   │   ├── cli/
│   │   │   │   └── main.py              CLI entry point (8 commands + run group)
│   │   │   └── schemas/
│   │   │       ├── team.py             Pydantic models (request/response)
│   │   │       ├── task.py
│   │   │       ├── session.py
│   │   │       ├── human_request.py
│   │   │       └── review.py
│   │   └── tests/                      395 tests across 18 files
│   │
│   ├── mcp-server/                     TypeScript — MCP tools
│   │   ├── src/
│   │   │   ├── index.ts                58 tool definitions
│   │   │   └── client.ts               Typed HTTP client
│   │   ├── tsconfig.json
│   │   └── package.json
│   │
│   └── frontend/                       React 19 + Vite
│       ├── src/
│       │   ├── main.tsx                Entry point
│       │   ├── App.tsx                 Root component
│       │   └── api/client.ts           Typed API client
│       ├── vite.config.ts              Proxy config
│       └── tsconfig.json
│
└── docs/                               Documentation
    ├── architecture.md                 System design, data flow
    ├── database.md                     All tables, relationships
    ├── tasks.md                        State machine, DAG, events
    ├── mcp-tools.md                    58 tools with parameters
    └── development.md                  (this file)
```

## Code Patterns

### API Route → Service → EventStore

```
POST /api/v1/teams/{id}/tasks
  → api/tasks.py: create_task()        HTTP handling
    → services/task_service.py          Business logic
      → events/store.py: append()       Record event
      → db session commit               Persist
```

Routes handle HTTP concerns (status codes, error mapping). Services handle business logic. The EventStore handles event persistence.

### FastAPI Dependency Injection

```python
def _task_svc(db: AsyncSession = Depends(get_db)) -> TaskService:
    return TaskService(db)

@router.post("/teams/{team_id}/tasks")
async def create_task(body: TaskCreate, svc: TaskService = Depends(_task_svc)):
    return await svc.create_task(...)
```

### Pydantic Schemas

Separate `Create` (input) from `Read` (output) schemas:

```python
class TaskCreate(BaseModel):    # What the client sends
    title: str
    priority: str = "medium"

class TaskRead(BaseModel):      # What the API returns
    id: int
    title: str
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}
```

### Constructor Injection (ExecutionLoop / AgentRunner)

Both `ExecutionLoop` and `AgentRunner` accept an optional `session_factory` parameter. In production, the default lazy import is used. In tests, a savepoint-wrapped factory is injected:

```python
# Production — default factory
loop = ExecutionLoop()

# Tests — inject savepoint-wrapped factory
loop = ExecutionLoop(session_factory=_make_session_factory(db_session))
```

This eliminates fragile `patch()` calls and makes tests deterministic. The `AgentRunner` receives the same factory from `ExecutionLoop`:

```python
runner = AgentRunner(session_factory=self._session_factory)
```

### Auth Patterns

Endpoints can require authentication via FastAPI dependencies:

```python
from openclaw.auth.dependencies import get_current_user, CurrentIdentity

@router.get("/protected")
async def protected_endpoint(identity: CurrentIdentity = Depends(get_current_user)):
    # identity.identity_type = "user" or "api_key"
    # identity.user_id or identity.org_id
    ...
```

Supports both JWT Bearer tokens and `x-api-key` header authentication.

## E2E Testing

End-to-end tests exercise the full stack (backend + real agent adapters) and are gated behind a marker so they don't run in normal CI:

```bash
cd packages/backend
uv run pytest tests/ --run-e2e          # run E2E tests (requires running infra)
uv run pytest tests/ --run-e2e -v -k e2e  # run only E2E tests
```

E2E tests are decorated with `@pytest.mark.e2e` and are skipped by default unless the `--run-e2e` flag is passed. They require a running PostgreSQL and Redis instance, and may require valid API keys for external services (Anthropic, OpenAI).

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_agent_workflow(client):
    """Requires --run-e2e flag and running infrastructure."""
    ...
```

## Adapter Development

To add support for a new AI coding agent, create a new adapter in `packages/backend/src/openclaw/agent/adapters/`.

### Steps

1. Create a new file (e.g., `my_agent.py`)
2. Subclass `AgentAdapter`
3. Implement `run()` — launch the agent process, return the result
4. Implement `build_prompt()` — format the task into agent-specific instructions
5. Register the adapter in the adapter registry

### Adapter Interface

```python
from openclaw.agent.adapters.base import AgentAdapter

class MyAgentAdapter(AgentAdapter):
    name = "my-agent"

    def build_prompt(self, task, repo, worktree_path: str) -> str:
        """Format the task into agent-specific instructions."""
        return f"Work on: {task.title}\n\n{task.description}"

    async def run(self, prompt: str, worktree_path: str, model: str) -> str:
        """Launch the agent process and return its output."""
        # Spawn subprocess, capture output, return result
        ...
```

### Built-in Adapters

| Adapter | File | Agent |
|---------|------|-------|
| Claude Code | `claude_code.py` | `claude` CLI with `--print` mode |
| Codex | `codex.py` | OpenAI `codex` CLI |
| Aider | `aider.py` | `aider` with `--message` flag |

## Docker Development

### Development

The standard `docker-compose.yml` at the project root starts just PostgreSQL and Redis for local development.

### Production

A production-ready Docker Compose configuration is available:

```bash
docker compose -f docker-compose.prod.yml up -d
```

This starts the full stack: PostgreSQL, Redis, the FastAPI backend, the MCP server, and the frontend.

### Dockerfiles

- `packages/backend/Dockerfile` — Multi-stage build for the Python backend
- `packages/mcp-server/Dockerfile` — Node.js build for the MCP server
- `packages/frontend/Dockerfile` — Vite build + nginx for the frontend

### Environment Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your values (database URL, API keys, JWT secret, etc.)
```

## Makefile

A `Makefile` at the project root provides shortcuts for common operations:

```bash
make help           # show all available targets
make dev            # start development infrastructure (Postgres + Redis)
make test           # run all tests
make test-e2e       # run E2E tests
make build          # build all packages
make lint           # run linters
make migrate        # run database migrations
make docker-up      # start production stack
make docker-down    # stop production stack
make clean          # clean build artifacts
```

Run `make help` to see the full list of available targets and their descriptions.
