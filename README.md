<p align="center">
  <img src="docs/assets/banner.svg" alt="Entourage" width="100%" />
</p>

<p align="center">
  <strong>Ship code with AI teams, not AI chat.</strong>
  <br />
  One command turns intent into planned, executed, reviewed, and merged code — with budget controls, human checkpoints, and full audit trails.
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

## The 30-second pitch

```bash
entourage run "Add rate limiting middleware to all API routes"
```

That single command:
1. **Creates** a run from your intent
2. **Plans** a task graph (AI-generated or template-based — works without an API key)
3. **Dispatches** agents to work in parallel, in isolated git worktrees
4. **Pauses** when agents hit ambiguity — they ask you, not guess
5. **Reviews** code with file-anchored comments and approve/reject verdicts
6. **Merges** via a managed queue with squash/rebase strategies

Every step is event-sourced. Every dollar is tracked. Nothing ships without your approval.

## Why not just use Claude / Codex directly?

You should. Entourage doesn't replace your coding agent — it gives it an engineering org to work inside.

| | Solo agent | With Entourage |
|:--|:-----------|:---------------|
| **Work intake** | Copy-paste into chat | `run "intent"` → task graph → execution |
| **Coordination** | One agent, one thread | Multiple agents working in parallel across tasks |
| **Memory** | Context window only | Persistent tasks, events, sessions — survives restarts |
| **Safety** | Hope for the best | Budget caps, state machine, human checkpoints |
| **Review** | Read the chat output | File-anchored comments, approve/reject/request-changes |
| **Ambiguity** | Agent guesses | Agent calls `ask_human` and waits for your answer |
| **Isolation** | Shared workspace | Branch-per-task git worktrees — agents can't stomp each other |
| **Audit** | Scroll through chat history | Immutable event store (who did what, when, why) |
| **Cost** | Check the Anthropic dashboard | Per-session, per-task, per-team tracking with daily caps |

## Screenshots

<table>
<tr>
<td width="50%">
<strong>Dashboard</strong> — Active tasks, agent status, cost tracking
<br /><br />
<img src="docs/assets/screenshot-dashboard.png" alt="Dashboard" width="100%" />
</td>
<td width="50%">
<strong>Runs</strong> — Create, plan, approve, and monitor execution
<br /><br />
<img src="docs/assets/screenshot-pipelines.png" alt="Runs" width="100%" />
</td>
</tr>
<tr>
<td width="50%">
<strong>Task Graph</strong> — Dependency DAG with complexity ratings and live status
<br /><br />
<img src="docs/assets/screenshot-pipeline-detail.png" alt="Run Detail" width="100%" />
</td>
<td width="50%">
<strong>Analytics</strong> — Run health, cost trends, agent efficiency
<br /><br />
<img src="docs/assets/screenshot-analytics.png" alt="Analytics" width="100%" />
</td>
</tr>
<tr>
<td colspan="2">
<strong>Teams & Agents</strong> — Multi-team management with role badges, model selection, and live status
<br /><br />
<img src="docs/assets/screenshot-manage.png" alt="Teams & Agents" width="100%" />
</td>
</tr>
</table>

## How it works

```
You say "Add rate limiting"
         │
         ▼
┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Run CLI        │────▶│  Task Planner    │────▶│  Execution     │
│  entourage run  │     │  AI or template  │     │  Loop          │
└─────────────────┘     └──────────────────┘     └───────┬────────┘
                                                         │
                              ┌───────────────────────────┼────────────────┐
                              │                           │                │
                              ▼                           ▼                ▼
                     ┌────────────────┐         ┌────────────────┐  ┌──────────┐
                     │  Agent 1       │         │  Agent 2       │  │  Agent 3 │
                     │  (Claude Code) │         │  (Codex)       │  │  (Aider) │
                     │  worktree: A   │         │  worktree: B   │  │  wt: C   │
                     └───────┬────────┘         └───────┬────────┘  └────┬─────┘
                             │                          │                │
                             ▼                          ▼                ▼
                     ┌──────────────────────────────────────────────────────────┐
                     │  58 MCP Tools — tasks, git, reviews, sessions, budgets  │
                     ├──────────────────────────────────────────────────────────┤
                     │  FastAPI Backend — PostgreSQL + Redis + Event Store      │
                     └──────────────────────────────────────────────────────────┘
```

Agents connect via [MCP](https://modelcontextprotocol.io) (Model Context Protocol). The backend manages all state. Humans stay in control through the dashboard, CLI, or API.

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

# 5. Ship something
cd packages/backend
uv run entourage login
uv run entourage run "Add a healthcheck endpoint at /health"
```

> **Prerequisites:** Docker Desktop, Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 18+
>
> **No Anthropic API key?** No problem. The planner falls back to built-in templates (feature, bugfix, refactor, migration) so the full platform works without any AI provider configured.

## Core capabilities

<table>
<tr>
<td width="50%">

**Run-driven execution**
- Intent → task graph → parallel execution → review → merge
- AI planner decomposes work into dependency DAGs
- Template fallback when no AI provider is configured
- `entourage run` one-liner or step-by-step control

**Governed task workflow**
- 7-state machine with enforced transitions
- DAG dependencies — Task B blocks until Task A completes
- Full event-sourced audit trail for every action

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

**Multi-agent teams**
- Org → team → agent hierarchy with role-based access
- Manager agents delegate to engineer agents
- PG LISTEN/NOTIFY instant dispatch
- Concurrent execution with configurable limits

**Production integrations**
- GitHub webhooks auto-create tasks from issues/PRs
- JWT + API key auth with org-scoped access
- Real-time dashboard via WebSocket + Redis pub/sub
- 3 agent adapters: Claude Code, Codex, Aider

</td>
</tr>
</table>

## CLI

```bash
# Run lifecycle (the main workflow)
entourage run INTENT                 # One-liner: create → plan → approve → execute
entourage run list                   # List all runs for the current team
entourage run create INTENT          # Create a new run (--template, --budget)
entourage run status ID              # Show run status, tasks, and progress
entourage run plan ID                # Start AI/template planning for a run
entourage run approve ID             # Approve the plan and start execution
entourage run tasks ID               # Show task graph with dependencies

# Quick dispatch (single agent, no planning)
entourage dispatch PROMPT            # Create task → assign → run agent directly

# Team & agent management
entourage status                     # Team overview (agents, tasks, requests)
entourage agents                     # List agents and their current state
entourage tasks [--status STATUS]    # List tasks with optional filter
entourage adapters                   # Show available adapters + readiness
entourage respond REQUEST_ID MSG     # Respond to a human-in-the-loop request
entourage login [--api-key KEY]      # Authenticate (JWT or API key)
entourage logout                     # Remove stored credentials
```

## MCP tools

58 tools across 14 categories. Agents discover and call these via the [Model Context Protocol](https://modelcontextprotocol.io).

| Category | Tools | # |
|----------|-------|:-:|
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
| **Runs** | `create_run` `get_run` `list_runs` `plan_run` `approve_run` `get_run_tasks` `cancel_run` `retry_run` | 8 |

## Agent adapters

Entourage dispatches work to pluggable coding agent backends:

| Adapter | CLI | MCP Support | Notes |
|---------|-----|:-----------:|-------|
| **Claude Code** | `claude` | ✅ Native | Full MCP integration via `--mcp-config` |
| **Codex** | `codex` | ✅ Native | OpenAI's agent with `--full-auto --mcp-config` |
| **Aider** | `aider` | ❌ REST | No MCP; prompt includes curl-based API instructions |

Check adapter availability: `entourage adapters`

## Architecture

```
packages/
  backend/        Python — FastAPI + SQLAlchemy 2.0 async + Alembic
  mcp-server/     TypeScript — 58 MCP tool definitions
  frontend/       React 19 + Vite 6 + TanStack Query
```

15 database models, 9 Alembic migrations, 11 API routers, event sourcing throughout.

**Key patterns:**
- **Constructor injection** — `ExecutionLoop` and `AgentRunner` accept `session_factory` for full testability without monkeypatching
- **Template planner fallback** — Built-in task decomposition templates when no AI provider is configured
- **Lazy client init** — External API clients created on first use, not at import time

## Tests

```bash
cd packages/backend
uv run pytest tests/ -v          # 395 tests, ~23s
uv run pytest tests/ --run-e2e   # Include live agent E2E tests
```

Per-test savepoint rollback — fully isolated, no cleanup, runs against real Postgres. Includes a full lifecycle integration test: task creation → assignment → human-in-the-loop → code review → approval → merge → done.

## Documentation

| Guide | What you'll learn |
|-------|-------------------|
| [Getting Started](docs/guides/getting-started.md) | Zero to a working AI team in 5 minutes |
| [Daily Workflow](docs/guides/daily-workflow.md) | What a typical day looks like with governed agents |
| [Multi-Agent Teams](docs/guides/multi-agent-team.md) | Manager + engineers coordinating on complex features |
| [Cost Control](docs/guides/cost-control.md) | Budget caps, per-task tracking, preventing runaway spend |
| [Webhook Automation](docs/guides/webhook-automation.md) | GitHub issues auto-create tasks for your agents |

| Reference | What's inside |
|-----------|--------------|
| [Architecture](docs/architecture.md) | System design, data flow, DI patterns, planner service |
| [Database Schema](docs/database.md) | 15 tables, relationships, migrations |
| [Task State Machine](docs/tasks.md) | Transitions, DAG, review flow, event types |
| [MCP Tools Reference](docs/mcp-tools.md) | All 58 tools with parameters and examples |
| [Development Guide](docs/development.md) | Setup, testing, patterns, project structure |

## Examples

Runnable scripts — each handles auth automatically (registers a fresh user per run):

```bash
python examples/quickstart.py           # Full lifecycle in 30 seconds
python examples/multi_agent.py          # Batch task DAG + two agents coordinating
python examples/human_in_the_loop.py    # Agent pauses, asks human, continues
python examples/code_review_flow.py     # Review → comments → approve → merge
python examples/webhook_automation.py   # GitHub webhook + HMAC verification
python examples/batch_orchestration.py  # DAG decomposition + 4 specialist agents
```

## Roadmap

| Phase | What | Status |
|:-----:|------|:------:|
| 0-4 | Foundation: MCP, orgs, tasks, git, sessions, cost tracking | ✅ |
| 5-8 | Core: real-time dashboard, dispatch, human-in-the-loop, code review | ✅ |
| 9-12 | Production: auth, webhooks, CLI, agent adapters (Claude Code, Codex, Aider) | ✅ |
| 13-17 | Polish: merge worker, multi-agent orchestration, E2E tests, full docs | ✅ |
| 18-19 | Architecture: UX overhaul, DI refactor, run CLI, template planner | ✅ |
| 20 | Project config (`ENTOURAGE.md` in-repo workflow policy) | 🔜 |
| 21 | Issue tracker integration (Linear, GitHub Issues) | 🔜 |
| 22 | Proof-of-work validation (CI status, test results before review) | 🔜 |

## License

MIT
