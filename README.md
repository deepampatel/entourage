<p align="center">
  <img src="docs/assets/banner.svg" alt="Entourage" width="100%" />
</p>

<p align="center">
  <strong>One agent writes code. An entourage ships it.</strong>
  <br />
  The orchestration layer that turns solo AI agents into governed, coordinated engineering teams.
  <br /><br />
  <a href="https://modelcontextprotocol.io">MCP-native</a> · Event-sourced · Human-in-the-loop
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-395_passing-6366f1?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/MCP_tools-58-8b5cf6?style=flat-square" alt="MCP Tools" />
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/TypeScript-5.0+-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License" />
</p>

---

## Why not just use Claude?

You absolutely should. Entourage doesn't replace your agent — it gives it a production-grade backbone.

| Solo agent | With Entourage |
|:-----------|:---------------|
| One agent, one chat thread | Multiple agents coordinated across tasks |
| Context window is the only memory | Persistent tasks, events, sessions — survive restarts |
| No spending limits — hope for the best | Per-session and daily budget caps, cost tracking per task |
| Freeform execution — anything goes | State machine enforces valid transitions (can't merge without review) |
| You manually review everything | Structured review cycles with file-anchored comments and verdicts |
| Agent works silently until done | Agent pauses to ask you questions, waits for approval |
| Code goes straight to a branch | Isolated git worktrees per task — agents can't stomp each other |
| Chat history is the audit trail | Every action is an immutable event (who did what, when, why) |
| You trigger work manually | GitHub webhooks auto-create tasks from issues and PRs |
| One project, one person | Multi-tenant: orgs → teams → agents, API key scoping |

**In short:** Claude is the developer. Entourage is the engineering org that developer works inside — with task boards, code review, access controls, cost tracking, and human oversight.

## How it works

```
┌─────────────┐         ┌─────────────┐         ┌──────────────┐
│  AI Agents  │──MCP───▶│  Entourage  │◀──HTTP──│   Dashboard  │
│  (Claude,   │  stdio  │   Backend   │         │   (React)    │
│   etc.)     │◀────────│             │────────▶│              │
└─────────────┘         └──────┬──────┘         └──────────────┘
                               │
                    ┌──────────┼──────────┐
                    │          │          │
               PostgreSQL    Redis      Git
              (all state)  (pub/sub)  (worktrees)
```

1. You define tasks. Entourage assigns them to agents.
2. Agents write code in isolated git worktrees via MCP tools.
3. When stuck, agents **ask humans** — and wait for a response.
4. Finished work goes through **code review** with approve/reject/request-changes.
5. Approved tasks merge via a managed queue. Every step is event-sourced.

Humans stay in control. Agents stay productive. Nothing ships without oversight.

## What you get

<table>
<tr>
<td width="50%">

**Governed task workflow**
- 7-state machine with enforced transitions
- DAG dependencies — Task B blocks until Task A completes
- Full event-sourced audit trail for every action

**Safe git operations**
- Branch-per-task with isolated worktrees
- Agents can't interfere with each other's code
- Merge queue with rebase/squash strategies

**Cost controls**
- Per-session token and dollar tracking
- Daily and per-task budget caps
- Kill a runaway agent before it burns your API credits

</td>
<td width="50%">

**Human oversight**
- Agents pause and ask before risky decisions
- File-anchored review comments (not just "LGTM")
- Approve / reject / request-changes verdicts

**Multi-agent coordination**
- PG LISTEN/NOTIFY instant dispatch
- Message routing between agents
- Concurrent agent execution with semaphore limits

**Production-ready integrations**
- GitHub webhooks → auto-create tasks from issues/PRs
- JWT + API key auth with org-scoped access
- Real-time dashboard via WebSocket + Redis pub/sub

</td>
</tr>
</table>

## Quick start

```bash
# 1. Infrastructure
docker compose up -d              # Postgres 16 + Redis 7

# 2. Backend
cd packages/backend
uv sync && uv run alembic upgrade head
uv run uvicorn openclaw.main:app --reload

# 3. MCP server
cd packages/mcp-server
npm install && npm run build

# 4. Frontend dashboard
cd packages/frontend
npm install && npm run dev        # http://localhost:5173

# 5. CLI — ship something
cd packages/backend
uv run entourage login
uv run entourage pipeline go "Add a healthcheck endpoint at /health"
```

The `pipeline go` command does everything: creates the pipeline, plans tasks (AI or template-based), auto-approves, and starts execution. One line from intent to running agents.

> **Prerequisites:** Docker Desktop, Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 18+
>
> **No Anthropic API key?** No problem. The planner falls back to template-based task decomposition (feature, bugfix, refactor, migration) so the full platform works without any AI provider configured.

## MCP tools

50 tools across 14 categories. Agents discover and call these via the [Model Context Protocol](https://modelcontextprotocol.io).

| Category | Tools | Count |
|----------|-------|:-----:|
| **Platform** | `ping` | 1 |
| **Orgs & Teams** | `list_orgs` `create_org` `list_teams` `create_team` `get_team` | 5 |
| **Agents** | `list_agents` `create_agent` | 2 |
| **Repos** | `list_repos` `register_repo` | 2 |
| **Tasks** | `create_task` `list_tasks` `get_task` `update_task` `change_task_status` `assign_task` `get_task_events` | 7 |
| **Messages** | `send_message` `get_inbox` | 2 |
| **Git** | `create_worktree` `get_worktree` `remove_worktree` `get_task_diff` `get_changed_files` `read_file` `get_commits` | 7 |
| **Sessions** | `start_session` `record_usage` `end_session` `check_budget` `get_cost_summary` | 5 |
| **Human-in-the-loop** | `ask_human` `get_pending_requests` `respond_to_request` | 3 |
| **Reviews** | `request_review` `approve_task` `reject_task` `get_merge_status` `get_review_feedback` | 5 |
| **Auth** | `authenticate` | 1 |
| **Webhooks** | `create_webhook` `list_webhooks` `update_webhook` | 3 |
| **Settings** | `get_team_settings` `update_team_settings` `get_team_conventions` `add_team_convention` | 4 |
| **Orchestration** | `create_tasks_batch` `wait_for_task_completion` `list_team_agents` | 3 |

## Architecture

```
packages/
  backend/        Python — FastAPI + SQLAlchemy 2.0 + Alembic
  mcp-server/     TypeScript — 47 MCP tool definitions
  frontend/       React 19 + Vite + TanStack Query
```

15 database models, 8 Alembic migrations, 11 API routers, event sourcing throughout.

**Key architectural patterns:**
- **Dependency injection** — `ExecutionLoop` and `AgentRunner` accept a `session_factory` parameter (constructor injection with lazy fallback), making them fully testable without monkeypatching
- **Template-based planner fallback** — When no `ANTHROPIC_API_KEY` is set, the `PlannerService` generates task graphs from built-in templates (feature, bugfix, refactor, migration) instead of calling Claude
- **Lazy client initialization** — External API clients (Anthropic) are only created when actually needed, preventing crashes from missing config

### Agent Adapters

Entourage dispatches work to pluggable coding agent backends:

| Adapter | CLI | MCP Support | Notes |
|---------|-----|:-----------:|-------|
| **Claude Code** | `claude` | ✅ Native | Full MCP integration via `--mcp-config` |
| **Codex** | `codex` | ✅ Native | OpenAI's agent with `--full-auto --mcp-config` |
| **Aider** | `aider` | ❌ REST | No MCP; prompt includes curl-based API instructions |

Check adapter availability: `entourage adapters`

### CLI Reference

```bash
# Team & agent management
entourage status                     # Show team status (agents, tasks, requests)
entourage agents                     # List agents and their current state
entourage tasks [--status STATUS]    # List tasks with optional filter
entourage run AGENT_ID [--task N]    # Dispatch an agent to work on a task
entourage adapters                   # Show available adapters + readiness
entourage respond REQUEST_ID MSG     # Respond to a human-in-the-loop request
entourage login [--api-key KEY]      # Authenticate (JWT or API key)
entourage logout                     # Remove stored credentials

# Pipeline lifecycle
entourage pipeline go INTENT         # One-liner: create → plan → approve → execute
entourage pipeline list              # List all pipelines for the current team
entourage pipeline create INTENT     # Create a new pipeline (--template, --budget)
entourage pipeline status ID         # Show pipeline status, tasks, and progress
entourage pipeline plan ID           # Start AI/template planning for a pipeline
entourage pipeline approve ID        # Approve the plan and start execution
entourage pipeline tasks ID          # Show task graph with dependencies
```

## Tests

```bash
cd packages/backend
uv run pytest tests/ -v          # 395 tests, ~23s
uv run pytest tests/ --run-e2e   # Include live agent E2E tests
```

Per-test savepoint rollback — fully isolated, no cleanup, runs against real Postgres.
Includes a full lifecycle integration test exercising: task creation → assignment → human-in-the-loop → code review → approval → merge → done.

## Guides

Learn how to actually use Entourage day-to-day:

| Guide | What you'll learn |
|-------|-------------------|
| [Getting Started](docs/guides/getting-started.md) | Zero to a working AI team in 5 minutes |
| [Daily Workflow](docs/guides/daily-workflow.md) | What a typical day looks like with governed agents |
| [Multi-Agent Teams](docs/guides/multi-agent-team.md) | Manager + engineers coordinating on complex features |
| [Cost Control](docs/guides/cost-control.md) | Budget caps, per-task tracking, preventing runaway spend |
| [Webhook Automation](docs/guides/webhook-automation.md) | GitHub issues auto-create tasks for your agents |

## Examples

Runnable scripts you can try right now ([examples/](examples/)). All examples handle auth automatically — each run registers a fresh user and authenticates via JWT.

```bash
python examples/quickstart.py           # Full lifecycle in 30 seconds
python examples/multi_agent.py          # Batch task DAG + two agents coordinating
python examples/human_in_the_loop.py    # Agent pauses, asks human, continues
python examples/code_review_flow.py     # Review → comments → approve → merge
python examples/webhook_automation.py   # GitHub webhook + HMAC verification
python examples/batch_orchestration.py  # DAG decomposition + 4 specialist agents
```

## Documentation

| Doc | What's inside |
|-----|--------------|
| [Architecture](docs/architecture.md) | System design, data flow, subsystems |
| [Database Schema](docs/database.md) | 15 tables, relationships, migrations |
| [Task State Machine](docs/tasks.md) | Transitions, DAG, review flow, event types |
| [MCP Tools Reference](docs/mcp-tools.md) | All 47 tools with parameters |
| [Development Guide](docs/development.md) | Setup, testing, patterns, project structure |

## Roadmap

| Phase | What | Status |
|:-----:|------|:------:|
| 0 | Project skeleton + MCP | ✅ |
| 1 | Orgs, teams, agents, repos | ✅ |
| 2 | Tasks, state machine, messages, events | ✅ |
| 3 | Git integration (worktrees, branch-per-task) | ✅ |
| 4 | Agent sessions + cost controls | ✅ |
| 5 | Real-time dashboard (WebSocket + Redis) | ✅ |
| 6 | Multi-agent dispatch (PG LISTEN/NOTIFY) | ✅ |
| 7 | Human-in-the-loop (approvals, questions) | ✅ |
| 8 | Code review + merge worker | ✅ |
| 9 | Auth + multi-tenant (JWT, API keys) | ✅ |
| 10 | Webhooks + team settings | ✅ |
| 11 | Agent adapters + CLI + runner | ✅ |
| 12 | Codex + Aider adapters | ✅ |
| 13 | Merge worker (git merge/rebase/squash) | ✅ |
| 14 | Auth on all API routes + CLI login | ✅ |
| 15 | Dashboard polish (human requests, reviews, agent status) | ✅ |
| 16 | Multi-agent orchestration (batch tasks, wait, team agents) | ✅ |
| 17 | Full-flow E2E test + docs | ✅ |
| 18 | UX overhaul — onboarding, toasts, guided empty states | ✅ |
| 19 | Architecture — DI refactor, pipeline CLI, template planner | ✅ |

## License

MIT
