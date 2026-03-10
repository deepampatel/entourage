# Getting Started with Entourage

This guide takes you from zero to a working AI engineering team in about 5 minutes.

By the end, you'll have an org, a team with agents, a registered repo, and your first task assigned and running.

## Prerequisites

| What | Why |
|------|-----|
| [Docker Desktop](https://docker.com/products/docker-desktop/) | Runs Postgres 16 + Redis 7 |
| Python 3.12+ with [uv](https://docs.astral.sh/uv/) | Backend runtime |
| Node.js 18+ | MCP server + frontend |

## Step 1: Start infrastructure

```bash
git clone https://github.com/deepampatel/openclaw.git
cd openclaw
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `5433` (not 5432, to avoid conflicts)
- **Redis 7** on port `6379`

Verify both are healthy:

```bash
docker compose ps
# Both should show "healthy"
```

## Step 2: Configure environment variables

Copy the example environment file and edit it with your settings:

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, JWT secret, etc.
```

See `.env.example` for all available configuration options including rate limits, JWT settings, and adapter paths.

## Step 3: Start the backend

```bash
cd packages/backend
uv sync                         # install dependencies
uv run alembic upgrade head     # create database tables
uv run uvicorn openclaw.main:app --reload --port 8000
```

Check it's running:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","postgres":true,"redis":true}
```

You now have a fully operational Entourage backend with 60+ API endpoints.

## Step 4: Install and authenticate the CLI

The Entourage CLI gives you commands for managing agents, tasks, pipelines, and adapters from your terminal.

```bash
cd packages/backend
uv sync   # installs the CLI as part of the backend package
```

Log in with your API key:

```bash
uv run entourage login --api-key oc_your_key_here
```

Verify your connection:

```bash
uv run entourage status
```

Check which agent adapters are available:

```bash
uv run entourage adapters
```

Entourage ships with 3 agent adapters out of the box: **Claude Code**, **Codex**, and **Aider**. Use `entourage adapters` to see which are configured and ready.

### CLI commands

| Command | What it does |
|---------|-------------|
| `entourage status` | Team status (agents, tasks, requests) |
| `entourage agents` | List agents and their state |
| `entourage tasks` | List tasks with optional status filter |
| `entourage run AGENT_ID` | Dispatch an agent to work on a task |
| `entourage respond REQUEST_ID MSG` | Respond to a human-in-the-loop request |
| `entourage adapters` | Show available adapters + readiness |
| `entourage login` | Authenticate (JWT or API key) |
| `entourage logout` | Remove stored credentials |
| `entourage pipeline go INTENT` | One-liner: create → plan → approve → execute |
| `entourage pipeline list` | List all pipelines for the current team |
| `entourage pipeline create INTENT` | Create a new pipeline |
| `entourage pipeline status ID` | Show pipeline status and progress |
| `entourage pipeline plan ID` | Start AI/template planning |
| `entourage pipeline approve ID` | Approve the plan and start execution |
| `entourage pipeline tasks ID` | Show task graph with dependencies |

## Step 5: Create your workspace

Every Entourage deployment starts with **Org → Team → Agents → Repo**.

### Create an org

```bash
curl -X POST http://localhost:8000/api/v1/orgs \
  -H "Content-Type: application/json" \
  -d '{"name": "My Company", "slug": "my-company"}'
```

Save the `id` from the response — you'll need it.

### Create a team

```bash
curl -X POST http://localhost:8000/api/v1/orgs/{org_id}/teams \
  -H "Content-Type: application/json" \
  -d '{"name": "Backend", "slug": "backend"}'
```

This auto-creates a **manager agent** for the team. The manager decomposes work and coordinates other agents.

### Add an engineer agent

```bash
curl -X POST http://localhost:8000/api/v1/teams/{team_id}/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "eng-1",
    "role": "engineer",
    "model": "claude-sonnet-4-20250514",
    "config": {"description": "Writes code, tests, and documentation"}
  }'
```

### Register your repo

```bash
curl -X POST http://localhost:8000/api/v1/teams/{team_id}/repos \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-project",
    "clone_url": "https://github.com/you/my-project.git",
    "default_branch": "main",
    "local_path": "/absolute/path/to/my-project"
  }'
```

Your workspace now looks like:

```
My Company (org)
  └── Backend (team)
        ├── manager (agent)
        ├── eng-1 (agent)
        └── my-project (repo)
```

## Step 6: Ship something

The fastest way to go from intent to running agents is the `pipeline go` command:

```bash
cd packages/backend
uv run entourage pipeline go "Add input validation to login endpoint"
```

This single command: creates a pipeline → plans tasks (AI or template-based) → auto-approves → starts execution. You can watch progress in real time.

> **No Anthropic API key?** No problem. The planner falls back to template-based task decomposition (feature, bugfix, refactor, migration) so the full platform works without any AI provider configured.

### Or do it step-by-step

If you prefer more control, use the individual pipeline commands:

```bash
# Create the pipeline
uv run entourage pipeline create "Add input validation to login endpoint" --template feature

# Plan the tasks (AI-generated or template-based)
uv run entourage pipeline plan {pipeline_id}

# Review the task graph
uv run entourage pipeline tasks {pipeline_id}

# Approve the plan and start execution
uv run entourage pipeline approve {pipeline_id}

# Check progress
uv run entourage pipeline status {pipeline_id}
```

### Or create tasks manually via API

You can also create individual tasks directly:

```bash
curl -X POST http://localhost:8000/api/v1/teams/{team_id}/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Add input validation to login endpoint",
    "description": "Validate email format and password length before hitting the database",
    "priority": "high",
    "task_type": "feature"
  }'
```

Assign it to an agent and move it to in-progress:

```bash
curl -X POST http://localhost:8000/api/v1/tasks/{task_id}/assign \
  -H "Content-Type: application/json" \
  -d '{"assignee_id": "{eng-1 agent id}"}'

curl -X POST http://localhost:8000/api/v1/tasks/{task_id}/status \
  -H "Content-Type: application/json" \
  -d '{"status": "in_progress"}'
```

## Step 7: Build the MCP server

The MCP server is how AI agents connect to Entourage. It exposes 58 tools via the Model Context Protocol.

```bash
cd packages/mcp-server
npm install
npm run build
```

### Connect from Claude Desktop

Add this to your Claude Desktop MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "entourage": {
      "command": "node",
      "args": ["/path/to/openclaw/packages/mcp-server/dist/index.js"],
      "env": {
        "OPENCLAW_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

Now Claude can call tools like `create_task`, `send_message`, `ask_human`, `request_review`, `create_tasks_batch`, `wait_for_task_completion`, `list_team_agents`, and 50+ more — all backed by Entourage's state management, auth, and audit trail.

## Step 8: Start the dashboard (optional)

```bash
cd packages/frontend
npm install
npm run dev
# → http://localhost:5173
```

The React dashboard shows real-time task status, agent activity, cost tracking, and human requests — all via WebSocket (authenticated using JWT token as a query parameter).

## What's next?

| Guide | What you'll learn |
|-------|-------------------|
| [Daily Workflow](daily-workflow.md) | How a typical day looks with Entourage |
| [Multi-Agent Teams](multi-agent-team.md) | Setting up agents that coordinate on complex work |
| [Cost Control](cost-control.md) | Budget caps, per-task tracking, preventing runaway spend |
| [Webhook Automation](webhook-automation.md) | Auto-creating tasks from GitHub issues and PRs |
