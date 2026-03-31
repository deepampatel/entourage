# Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        E N T O U R A G E                         │
│                                                                  │
│   ┌──────────┐    MCP (stdio)    ┌──────────────────────────┐   │
│   │ AI Agent │◄─────────────────►│     MCP Server (TS)      │   │
│   │ (Claude, │    58 tools       │  tasks, git, reviews,    │   │
│   │  etc.)   │                   │  sessions, webhooks, ... │   │
│   └──────────┘                   └────────────┬─────────────┘   │
│                                               │ REST             │
│   ┌──────────┐    WebSocket      ┌────────────▼─────────────┐   │
│   │  Human   │◄─────────────────►│    FastAPI Backend (Py)  │   │
│   │  Users   │    REST           │  ┌─────────────────────┐ │   │
│   │          │◄─────────────────►│  │   Service Layer     │ │   │
│   └──────────┘                   │  │  ┌───────────────┐  │ │   │
│        ▲                         │  │  │ State Machine │  │ │   │
│        │                         │  │  │ DAG Enforcer  │  │ │   │
│   ┌────┴─────┐                   │  │  │ Event Store   │  │ │   │
│   │  React   │                   │  │  │ Auth (JWT/API)│  │ │   │
│   │ Frontend │                   │  │  └───────────────┘  │ │   │
│   └──────────┘                   │  └─────────────────────┘ │   │
│                                  └────────────┬─────────────┘   │
│                                               │                  │
│        ┌──────────────────────────────────────┼──────────┐      │
│        │                     │                │          │      │
│  ┌─────▼─────┐    ┌─────────▼──┐   ┌────────▼──┐ ┌────▼───┐  │
│  │ PostgreSQL│    │ Dispatcher  │   │   Redis   │ │  Git   │  │
│  │    16     │    │ (LISTEN/    │   │     7     │ │Worktree│  │
│  │           │◄───│  NOTIFY)    │   │  pub/sub  │ │        │  │
│  └───────────┘    └────────────┘   └───────────┘ └────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Agent workflow
```
Agent calls               Backend validates              Database stores
─────────────────         ────────────────────           ─────────────────
create_task        →      TaskService.create()      →    tasks table + event
change_task_status →      state machine check       →    tasks table + event
                          dependency DAG check
send_message       →      MessageService.send()     →    messages table + event
                                                         + PG NOTIFY trigger
start_session      →      SessionService.start()    →    sessions table
ask_human          →      HumanLoopService.create() →    human_requests table
request_review     →      ReviewService.request()   →    reviews table + event
```

### Real-time dispatch
```
Message inserted → PG trigger → NOTIFY 'new_message' → Dispatcher picks up
                                                        → Routes to agent
                                                        → Agent processes turn
```

### Webhook flow
```
GitHub POST → /webhooks/{id}/receive → Verify HMAC-SHA256 signature
                                     → Log delivery in webhook_deliveries
                                     → Process event (create/update tasks)
                                     → Emit event via Redis pub/sub
```

## Request Lifecycle

1. **AI Agent** calls an MCP tool (e.g. `create_task`)
2. **MCP Server** (TypeScript) translates the tool call into an HTTP request
3. **FastAPI Backend** (Python) receives the request, routes it to the service layer
4. **Auth Layer** validates JWT token or API key (if endpoint is protected)
5. **Service Layer** validates business rules (state machine, DAG dependencies, budgets)
6. **EventStore** records the change as an immutable event
7. **Database** stores both the projection (tasks table) and the event
8. **PG Trigger** fires NOTIFY for relevant changes (messages, human requests, task status)
9. **Dispatcher** picks up notifications and routes work to agents
10. **Redis pub/sub** pushes the change to WebSocket clients (React dashboard)

## Layer Separation

```
MCP Tool Definition (index.ts)      What agents see (58 tools)
        │
        ▼
HTTP Client (client.ts)              Protocol bridge (MCP → HTTP)
        │
        ▼
API Route (api/*.py)                 HTTP translation + error handling
        │
        ▼
Auth (auth/dependencies.py)          JWT / API key verification
        │
        ▼
Service (services/*.py)              Business logic + state machine
        │
        ▼
EventStore (events/store.py)         Immutable event recording
        │
        ▼
SQLAlchemy Models (db/models.py)     Database schema (15 models)
```

Each layer has a single responsibility. API routes never contain business logic. Services never touch HTTP concepts. The EventStore is the only writer to the events table.

### Dependency Injection

`ExecutionLoop` and `AgentRunner` accept a `session_factory` parameter via constructor injection with lazy fallback:

```python
class ExecutionLoop:
    def __init__(self, session_factory=None) -> None:
        from openclaw.db.engine import async_session_factory
        self._session_factory = session_factory or async_session_factory
```

This makes both classes fully testable without monkeypatching — tests inject a savepoint-wrapped factory, production code uses the default. The `AgentRunner` is instantiated by `ExecutionLoop._run_task()` and receives the same factory:

```python
runner = AgentRunner(session_factory=self._session_factory)
```

### Manager-as-Planner (Phase 3)

The `PlannerService` dispatches the **manager agent** (Claude Code) to read the codebase and produce a context-aware task graph. The manager explores the project structure, understands existing patterns, and creates tasks with specific file paths and acceptance criteria.

**Planning flow:**
1. Manager agent runs in tmux with access to the full repo
2. Agent reads files, understands architecture, produces analysis
3. Analysis is converted to structured JSON via Claude API (`create_task_graph` tool)
4. RunTasks are created from the structured output

**Fallback chain** (always produces a plan):
- Manager agent analysis → API structured conversion → template fallback

When no `ANTHROPIC_API_KEY` is configured, the system uses built-in templates: **feature**, **bugfix**, **refactor**, **migration**, and **custom**.

### Tmux Runtime (Phase 3)

Agents run in tmux sessions instead of bare subprocesses:

```
┌────────────────────────────────────────────┐
│  tmux session: eo-task-365                 │
│  ┌──────────────────────────────────────┐  │
│  │  claude --print --mcp-config ...     │  │
│  │  (agent working on task)             │  │
│  └──────────────────────────────────────┘  │
│  stdout tee'd to output.txt               │
│  remain-on-exit: on (read output after)   │
└────────────────────────────────────────────┘
```

**Why tmux over subprocess:**
- **Live observation**: `tmux attach -t eo-task-365`
- **Crash survival**: tmux persists if the backend process dies
- **No stdout limits**: read output via `capture-pane` or tee file
- **Exit detection**: `remain-on-exit` + `pane_dead` flag check

**Launcher scripts** avoid shell quoting issues with multi-line prompts:
```bash
#!/bin/bash
claude --print --mcp-config /tmp/config.json \
  --allowedTools "mcp__entourage__*" \
  --max-turns 100 \
  "$(cat '/tmp/prompt.txt')" 2>&1 | tee "/tmp/output.txt"
```

### Atomic Agent Acquisition

The execution loop uses `FOR UPDATE SKIP LOCKED` to prevent double-dispatch:

```sql
UPDATE agents SET status = 'working'
WHERE id = (
    SELECT id FROM agents
    WHERE team_id = :team_id AND role = 'engineer' AND status = 'idle'
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id
```

Two tasks acquiring agents concurrently will never grab the same agent.

### Event-Driven Dispatch

Task completion triggers immediate re-dispatch via `asyncio.Event`:

```python
# In _run_task(), after agent finishes:
self._wakeup.set()  # Unblocks the main loop instantly

# In main loop, instead of sleep(10):
await asyncio.wait_for(self._wakeup.wait(), timeout=10.0)
```

This eliminates polling latency — the next task starts within milliseconds of its predecessor completing.

### Run Execution Loop

The `ExecutionLoop` manages the full run lifecycle: DRAFT → PLANNING → AWAITING_PLAN_APPROVAL → EXECUTING → REVIEWING → DONE. It handles parallel task dispatch with git worktree isolation, atomic agent acquisition, event-driven wakeup, retry logic, sandbox testing, and progress tracking — all with budget enforcement and graceful shutdown.

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Database | PostgreSQL 16 | JSONB, ARRAY, LISTEN/NOTIFY, triggers |
| Cache/Pubsub | Redis 7 | Real-time events, job queues, pub/sub |
| Backend | FastAPI + SQLAlchemy 2.0 async | Async-native, type-safe, dependency injection |
| Migrations | Alembic | Auto-generated from ORM model diffs + manual for triggers |
| Auth | PyJWT + SHA-256 | JWT access/refresh tokens, hashed API keys |
| Config | pydantic-settings | Env vars with `OPENCLAW_` prefix, validated types |
| MCP Server | TypeScript + @modelcontextprotocol/sdk | Typed tools, stdio transport |
| Frontend | React 19 + Vite + TanStack Query | Fast dev, server state management |
| Package mgmt | uv (Python), npm (Node) | uv is 10-100x faster than pip |
| Testing | pytest-asyncio + httpx | Async tests with savepoint rollback isolation |

## Multi-Tenant Model

```
Organization (Acme Corp)
  ├── API Key: oc_abc123... (SHA-256 hashed, org-scoped)
  ├── Webhook: GitHub → /webhooks/{id}/receive
  └── Team (Backend)
        ├── Config: {daily_cost_limit_usd: 100, auto_merge: true, ...}
        ├── Agent: manager (auto-created)
        ├── Agent: eng-1 (engineer)
        ├── Agent: eng-2 (engineer)
        ├── Repo: api-server
        ├── Task: Fix login bug
        │     ├── Event: task.created
        │     ├── Event: task.assigned → eng-1
        │     ├── Event: task.status_changed → in_progress
        │     ├── Session: 1500 tokens, $0.004
        │     ├── HumanRequest: "Should I refactor auth too?"
        │     ├── Review: attempt 1, verdict: approve
        │     └── MergeJob: status: success
        └── Message: manager → eng-1: "Work on login bug"
              └── PG NOTIFY → Dispatcher → eng-1 turn
```

Organizations are the top-level tenant boundary. Teams scope all work. Creating a team auto-provisions a manager agent.

## Key Subsystems

### Dispatcher (Phase 6)
PG LISTEN/NOTIFY-based agent dispatcher. Listens for:
- `new_message` — route message to recipient agent
- `human_request_resolved` — resume blocked agent
- `task_status_changed` — trigger dependent work

Features: semaphore-based concurrency (max 32), double-dispatch prevention, fallback poll loop, stale request cleanup.

### Auth (Phase 9)
Dual authentication:
- **JWT tokens** — For human users (60min access + 30-day refresh)
- **API keys** — For agents/CI (`oc_` prefix, SHA-256 hashed, org-scoped, optional expiry)

### Review Feedback Loop (Closed Loop)
When a reviewer gives `request_changes`, the system automatically:
1. Formats review comments into structured feedback
2. Transitions the task back to `in_progress`
3. Sends the feedback as a message to the assignee agent
4. PG NOTIFY fires → Dispatcher re-runs the agent with feedback in its inbox

The agent's prompt instructs it to check for review feedback before starting work, creating a fully automated review→fix→resubmit cycle.

### Webhook Receiver (Phase 10)
GitHub/GitLab webhook ingestion:
- HMAC-SHA256 signature verification
- Event filtering (configurable per webhook)
- Delivery audit trail (every payload logged)
- Auto-creates tasks from `issues.opened` and `pull_request.opened` events
- Maps GitHub labels to task priority (`critical`/`urgent`/`P0` → critical, etc.)
- Optional auto-assign to idle agents via `webhook.config.auto_assign`

### Agent Adapter System (Phase 11, upgraded in Phase 3)
Pluggable adapters that launch and manage external AI coding agents. Each adapter subclasses `AgentAdapter` and implements `run()` and `build_prompt()`. Common utilities (`_write_mcp_config`, `_build_conventions_section`, `_build_context_section`) live in the base class.

Three built-in adapters in `packages/backend/src/openclaw/agent/adapters/`:

| Adapter | Agent | Runtime | How it works |
|---------|-------|---------|-------------|
| `claude_code.py` | Claude Code | **tmux** | Launcher script in tmux session, `--print` mode, stdout tee'd to file. Fallback to subprocess if tmux unavailable. |
| `codex.py` | OpenAI Codex | subprocess | ⚠️ Deprecated (OpenAI sunset Codex). Spawns `codex` CLI. |
| `aider.py` | Aider | subprocess | Spawns `aider` with `--message` flag, reads result |

All adapters run in the task's worktree so changes are branch-isolated. The Claude Code adapter creates a launcher script to avoid shell quoting issues with multi-line prompts in tmux.

### New Services (Phase 3)

| Service | Purpose |
|---------|---------|
| `activity_detector.py` | Reads Claude Code JSONL session files for real-time agent state (active/idle/stuck/blocked) |
| `reaction_engine.py` | Automated responses to system events — stuck agent detection, rate limit pausing, auto-retry |
| `recovery.py` | Crash recovery on startup — resets stale sessions, orphaned tasks, stuck agents |
| `review_dedup.py` | SHA-256 fingerprinting prevents duplicate review comments |
| `sibling_context.py` | Injects parallel task awareness into agent prompts (what other agents are doing) |

### Team Conventions
Team coding conventions stored in `teams.config` JSONB (no migration needed). CRUD via `/settings/teams/{id}/conventions`. Active conventions are loaded by `AgentRunner` and injected into all adapter prompts — agents follow team standards automatically.

### Priority-Weighted Dispatch
The dispatcher's fallback poll query orders agents by task priority (`critical → high → medium → low`). Critical bugs get dispatched before low-priority cleanup work.

### Merge Worker (Phase 12)
Background task that polls the `merge_jobs` table for jobs with status `queued`. For each job:

1. Sets status to `running`
2. Checks out the task branch in the repo
3. Executes the merge strategy (`rebase`, `merge`, or `squash`)
4. On success: sets status to `success`, records the merge commit SHA, transitions the task to `done`
5. On failure: sets status to `failed`, records the error, transitions the task back to `in_progress`

The worker runs as part of the backend process and is started during application lifespan.

### Security Middleware (Phase 16)
Production-grade security hardening applied to all API routes:

- **Rate limiting** — Configurable per-endpoint rate limits to prevent abuse
- **Security headers** — Strict `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, and other headers via middleware
- **Request ID** — Every request gets a unique `X-Request-ID` header for tracing through logs
- **WebSocket auth** — WebSocket connections require a valid JWT token on the upgrade handshake
- **bcrypt** — Password hashing upgraded from SHA-256+salt to bcrypt for user accounts
