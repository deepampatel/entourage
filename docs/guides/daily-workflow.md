# Daily Workflow with Entourage

What does a typical day look like when you're running AI agents through Entourage instead of raw chatting with Claude? This guide walks through a realistic workday.

## The mental model

Without Entourage, working with AI agents looks like this:

```
You → Chat with Claude → Hope it does the right thing → Manually check everything
```

With Entourage:

```
You → Create tasks → Agents work in governed pipelines → You review and approve
```

The difference: **structure**. Tasks have states. Code has reviews. Budgets have limits. Every action has an audit trail.

## Morning: Check what happened overnight

If you have agents running async work, start by checking status via the CLI or dashboard:

```bash
# Quick overview — agents, tasks, pending requests
entourage status

# What tasks are in progress?
entourage tasks --status in_progress

# Check pipeline progress
entourage pipeline list
```

Or query the API directly:

```bash
curl http://localhost:8000/api/v1/teams/{team_id}/tasks
curl http://localhost:8000/api/v1/teams/{team_id}/human-requests
curl http://localhost:8000/api/v1/teams/{team_id}/costs
```

**Human requests are the critical ones.** If an agent hit something it wasn't sure about, it called `ask_human` and paused. You'll see questions like:

- "The API returns 500 for empty arrays. Should I return 200 with an empty list, or 204 No Content?"
- "Found 3 places where this function is called. Should I update all callers or add a backward-compatible wrapper?"

Respond via the API or dashboard:

```bash
curl -X POST http://localhost:8000/api/v1/human-requests/{request_id}/respond \
  -H "Content-Type: application/json" \
  -d '{"response": "Return 200 with empty array — our frontend expects it", "decision": "approved"}'
```

The agent gets unblocked and continues working.

## Mid-morning: Create new work

A bug report comes in. If you've set up [webhook automation](webhook-automation.md), the GitHub issue automatically becomes a task with the right priority (mapped from labels). Otherwise, use the pipeline CLI:

### The fast way — `pipeline go`

```bash
entourage pipeline go "Fix: login endpoint returns 500 for special characters in email"
```

One command: creates a pipeline → plans tasks → approves → starts execution. The template planner will auto-detect this as a bugfix and generate appropriate tasks (diagnose → fix → test).

### The controlled way — step by step

```bash
# Create the pipeline with a bugfix template
entourage pipeline create "Fix login 500 for special chars in email" --template bugfix

# Plan the tasks
entourage pipeline plan {pipeline_id}

# Review the task graph before approving
entourage pipeline tasks {pipeline_id}

# Approve and start execution
entourage pipeline approve {pipeline_id}
```

### Or create a single task manually

```bash
curl -X POST http://localhost:8000/api/v1/teams/{team_id}/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Fix: login endpoint returns 500 for special characters in email",
    "description": "Steps to reproduce: POST /auth/login with email containing + symbol. Expected: 400 validation error. Actual: 500 unhandled exception.",
    "priority": "high",
    "task_type": "bugfix"
  }'
```

Assign it to an agent:

```bash
curl -X POST http://localhost:8000/api/v1/tasks/{task_id}/assign \
  -H "Content-Type: application/json" \
  -d '{"assignee_id": "{eng-1 id}"}'
```

The agent picks it up through the MCP dispatcher. It will:

1. Create a **git worktree** (isolated branch, no conflicts with other agents)
2. Investigate the bug
3. Write a fix + tests
4. Request a **code review** when done

All of this is tracked. You can check progress anytime:

```bash
# Pipeline-level progress (all tasks at a glance)
entourage pipeline status {pipeline_id}
entourage pipeline tasks {pipeline_id}

# Individual task status + event history
curl http://localhost:8000/api/v1/tasks/{task_id}/events

# What files changed?
curl http://localhost:8000/api/v1/tasks/{task_id}/files

# See the diff
curl http://localhost:8000/api/v1/tasks/{task_id}/diff
```

## Afternoon: Review agent work

The agent finished the bug fix and requested review. You get notified via the dashboard (WebSocket push).

### Look at the review

```bash
# List reviews for the task
curl http://localhost:8000/api/v1/tasks/{task_id}/reviews
```

### Add comments on specific files

```bash
curl -X POST http://localhost:8000/api/v1/reviews/{review_id}/comments \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "src/openclaw/auth/password.py",
    "line_number": 42,
    "body": "Good fix, but also add a test for unicode characters in email"
  }'
```

### Give a verdict

```bash
# Request changes — agent will automatically go back and fix
curl -X POST http://localhost:8000/api/v1/reviews/{review_id}/verdict \
  -H "Content-Type: application/json" \
  -d '{"verdict": "request_changes", "body": "See comments — need one more test case"}'
```

**This triggers the automated feedback loop.** When you give `request_changes`:

1. Your review comments are formatted into structured feedback
2. The task transitions back to `in_progress`
3. The feedback is sent as a message to the assignee agent
4. The dispatcher re-runs the agent automatically
5. The agent reads the feedback via `get_review_feedback` and fixes the issues
6. The agent re-submits for review

No manual intervention needed — you just give the verdict and the agent handles the rest. This cycle continues until you approve:

```bash
curl -X POST http://localhost:8000/api/v1/reviews/{review_id}/verdict \
  -H "Content-Type: application/json" \
  -d '{"verdict": "approve", "body": "Looks good, ship it"}'
```

### Merge

```bash
curl -X POST http://localhost:8000/api/v1/tasks/{task_id}/merge \
  -H "Content-Type: application/json" \
  -d '{"strategy": "squash"}'
```

The task moves to `done`. The worktree is cleaned up. The event log shows the complete trail: created → assigned → in_progress → in_review → done.

## End of day: Check costs

```bash
curl http://localhost:8000/api/v1/teams/{team_id}/costs
```

You'll see per-agent, per-session breakdowns:

- eng-1: 3 sessions, 45k tokens, $0.12
- eng-2: 1 session, 12k tokens, $0.03

If an agent is burning through budget, you can cap it:

```bash
curl -X PATCH http://localhost:8000/api/v1/settings/teams/{team_id} \
  -H "Content-Type: application/json" \
  -d '{"daily_cost_limit_usd": 5.00}'
```

## Multi-agent orchestration

When you have a larger feature that involves multiple agents, the manager agent can coordinate the work using Entourage's orchestration tools. Instead of creating and assigning tasks one at a time, the manager creates batches, delegates, and waits for results.

### Check team capacity

Before assigning work, the manager checks who's available:

```bash
# Via MCP tool: list_team_agents
# Returns all agents on the team with their current status and active task count
curl http://localhost:8000/api/v1/teams/{team_id}/agents
```

This tells the manager which engineers are idle and ready for new work.

### Create tasks in batch

Instead of creating tasks one by one, use `create_tasks_batch` to create multiple tasks in a single call:

```bash
# Via MCP tool: create_tasks_batch
curl -X POST http://localhost:8000/api/v1/teams/{team_id}/tasks/batch \
  -H "Content-Type: application/json" \
  -d '{
    "tasks": [
      {
        "title": "Add rate limiting middleware",
        "description": "Apply 100 rpm default limit to all API routes, 10 rpm for auth endpoints",
        "priority": "high",
        "task_type": "feature",
        "assignee_id": "{eng-backend_id}"
      },
      {
        "title": "Add rate limit headers to frontend API client",
        "description": "Parse X-RateLimit-Remaining headers and show warnings",
        "priority": "medium",
        "task_type": "feature",
        "assignee_id": "{eng-frontend_id}"
      },
      {
        "title": "Write rate limiting integration tests",
        "description": "Test 429 responses, header presence, and per-route limits",
        "priority": "medium",
        "task_type": "feature",
        "assignee_id": "{eng-backend_id}",
        "depends_on": ["{task_1_id}"]
      }
    ]
  }'
```

All three tasks are created atomically. Dependencies are wired up. Agents are assigned and notified.

### Wait for completion

The manager doesn't need to poll. It calls `wait_for_task_completion` which blocks until all specified tasks reach a terminal state:

```bash
# Via MCP tool: wait_for_task_completion
curl -X POST http://localhost:8000/api/v1/tasks/wait \
  -H "Content-Type: application/json" \
  -d '{
    "task_ids": ["{task_1_id}", "{task_2_id}", "{task_3_id}"],
    "timeout_seconds": 3600
  }'
```

When all tasks complete (or the timeout is reached), the manager gets the results and can consolidate — writing a summary, creating a follow-up task, or marking the parent feature as done.

### The full orchestration loop

```
Manager receives feature request
    ↓
list_team_agents → check who's available
    ↓
create_tasks_batch → create sub-tasks + assign to engineers
    ↓
Engineers work in parallel (isolated worktrees)
    ↓
wait_for_task_completion → manager blocks until all sub-tasks finish
    ↓
Manager consolidates results → marks feature complete
```

This pattern replaces manual coordination. The manager agent handles decomposition, delegation, and follow-up automatically.

## The key patterns

### 1. Tasks, not chat threads

Instead of a conversation that gets lost when context runs out, you have persistent tasks with defined states. An agent can crash and restart — the task is still there, still assigned, still tracked.

### 2. Review before merge — always

No agent code goes to main without your explicit approval. The state machine enforces this: you can't transition from `in_review` to `done` without an approve verdict.

### 3. Questions, not assumptions

When agents hit ambiguity, they don't guess — they call `ask_human` and wait. This is the difference between "it rewrote my auth system" and "it asked me whether to use JWT or sessions."

### 4. Budget limits, not surprise bills

Set daily and per-task cost caps. Entourage tracks every token spent in every session. When a budget is exceeded, the agent is told to stop.

### 5. Team conventions, not repeated instructions

Instead of telling every agent "use pytest" and "follow PEP 8", set conventions once:

```bash
curl -X POST http://localhost:8000/api/v1/settings/teams/{team_id}/conventions \
  -H "Content-Type: application/json" \
  -d '{"key": "testing", "content": "Always write unit tests with pytest. Target 80% coverage."}'
```

Conventions are automatically injected into every agent's prompt. Add them once, enforce them forever.

### 6. Audit everything

Every state change, every assignment, every review verdict is an immutable event. Six months from now, you can trace exactly what happened on any task.

## Compared to raw Claude

| What you do | Raw Claude | With Entourage |
|-------------|-----------|----------------|
| Assign work | Paste context into chat | `create_task` + `assign_task` |
| Check progress | Scroll through chat | `get_task` / `get_task_events` |
| Review code | Read the chat output | `get_task_diff` + file-anchored comments |
| Approve changes | Say "looks good" | `approve_task` → auto-merge |
| Track costs | Check Anthropic dashboard manually | `check_budget` / `get_cost_summary` |
| Handle ambiguity | Agent guesses or asks in chat | `ask_human` — agent pauses and waits |
| Multiple agents | Open multiple chat windows | Dispatcher routes work automatically |
| Audit trail | Re-read old chats | Event store with immutable history |
