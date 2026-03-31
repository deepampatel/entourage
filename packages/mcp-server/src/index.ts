#!/usr/bin/env node
/**
 * OpenClaw MCP Server — the primary interface for OpenClaw agents.
 *
 * Learn: MCP (Model Context Protocol) is how AI agents discover and use tools.
 * This server exposes our platform's capabilities as MCP tools that any
 * MCP-compatible agent (OpenClaw, Claude, etc.) can call.
 *
 * Runs via stdio transport: OPENCLAW_API_URL=http://localhost:8000 node dist/index.js
 *
 * Tools grow with each phase:
 *   Phase 0: ping
 *   Phase 1: list_teams, get_team, list_agents, list_repos
 *   Phase 2: create_task, list_tasks, get_task, change_task_status, send_message, ...
 *   Phase 3: get_task_diff, get_task_files, ...
 *   Phase 4: start_session, record_usage, check_budget, run_command, read_file, ...
 *   Phase 7: ask_human, respond_to_request, ...
 *   Phase 8: approve_task, reject_task, ...
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import * as client from "./client.js";

const server = new McpServer({
  name: "openclaw",
  version: "0.1.0",
});

// ═══════════════════════════════════════════════════════════
// Phase 0: Foundation
// ═══════════════════════════════════════════════════════════

server.tool(
  "ping",
  "Check if the OpenClaw platform is reachable and healthy.",
  {},
  async () => {
    try {
      const health = await client.ping();
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(health, null, 2),
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error: ${error instanceof Error ? error.message : String(error)}`,
          },
        ],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 1: Teams / Agents / Repos
// ═══════════════════════════════════════════════════════════

/**
 * Helper: wraps a function with try/catch → MCP response format.
 * Every tool returns either { content: [...] } or { content: [...], isError: true }.
 */
function toolHandler(fn: () => Promise<unknown>) {
  return async () => {
    try {
      const result = await fn();
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Error: ${error instanceof Error ? error.message : String(error)}`,
          },
        ],
        isError: true,
      };
    }
  };
}

// ─── Organizations ──────────────────────────────────────────

server.tool(
  "list_orgs",
  "List all organizations.",
  {},
  toolHandler(() => client.listOrgs())
);

server.tool(
  "create_org",
  "Create a new organization.",
  { name: z.string().describe("Organization name"), slug: z.string().describe("URL-friendly slug (lowercase, hyphens)") },
  async (params) => {
    try {
      const org = await client.createOrg(params.name, params.slug);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(org, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ─── Teams ──────────────────────────────────────────────────

server.tool(
  "list_teams",
  "List all teams in an organization.",
  { org_id: z.string().describe("Organization UUID") },
  async (params) => {
    try {
      const teams = await client.listTeams(params.org_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(teams, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "create_team",
  "Create a new team in an organization. Auto-provisions a manager agent.",
  {
    org_id: z.string().describe("Organization UUID"),
    name: z.string().describe("Team name"),
    slug: z.string().describe("URL-friendly slug"),
  },
  async (params) => {
    try {
      const team = await client.createTeam(params.org_id, params.name, params.slug);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(team, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_team",
  "Get team details including agents and repositories.",
  { team_id: z.string().describe("Team UUID") },
  async (params) => {
    try {
      const team = await client.getTeam(params.team_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(team, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ─── Agents ─────────────────────────────────────────────────

server.tool(
  "list_agents",
  "List all agents in a team.",
  { team_id: z.string().describe("Team UUID") },
  async (params) => {
    try {
      const agents = await client.listAgents(params.team_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(agents, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "create_agent",
  "Create a new agent in a team.",
  {
    team_id: z.string().describe("Team UUID"),
    name: z.string().describe("Agent name"),
    role: z.string().describe("Agent role: manager, engineer, or reviewer").default("engineer"),
    model: z.string().describe("LLM model to use").default("claude-sonnet-4-20250514"),
  },
  async (params) => {
    try {
      const agent = await client.createAgent(
        params.team_id,
        params.name,
        params.role,
        params.model
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(agent, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ─── Repositories ───────────────────────────────────────────

server.tool(
  "list_repos",
  "List all repositories registered with a team.",
  { team_id: z.string().describe("Team UUID") },
  async (params) => {
    try {
      const repos = await client.listRepos(params.team_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(repos, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "register_repo",
  "Register a git repository with a team.",
  {
    team_id: z.string().describe("Team UUID"),
    name: z.string().describe("Repository name"),
    local_path: z.string().describe("Local filesystem path to the repo"),
    default_branch: z.string().describe("Default branch name").default("main"),
  },
  async (params) => {
    try {
      const repo = await client.registerRepo(
        params.team_id,
        params.name,
        params.local_path,
        params.default_branch
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(repo, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 2: Tasks / Messages
// ═══════════════════════════════════════════════════════════

// ─── Tasks ──────────────────────────────────────────────────

server.tool(
  "create_task",
  "Create a new task for a team. Starts in 'todo' status. Auto-generates a branch name.",
  {
    team_id: z.string().describe("Team UUID"),
    title: z.string().describe("Task title"),
    description: z.string().describe("Task description").default(""),
    priority: z.enum(["low", "medium", "high", "critical"]).describe("Task priority").default("medium"),
    assignee_id: z.string().describe("Agent UUID to assign").optional(),
    depends_on: z.array(z.number()).describe("Task IDs this task depends on").default([]),
    tags: z.array(z.string()).describe("Tags for categorization").default([]),
  },
  async (params) => {
    try {
      const task = await client.createTask(params.team_id, params.title, {
        description: params.description,
        priority: params.priority,
        assignee_id: params.assignee_id,
        depends_on: params.depends_on,
        tags: params.tags,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "list_tasks",
  "List tasks for a team. Can filter by status and assignee.",
  {
    team_id: z.string().describe("Team UUID"),
    status: z.string().describe("Filter by status (todo, in_progress, in_review, etc.)").optional(),
    assignee_id: z.string().describe("Filter by assigned agent UUID").optional(),
    include_archived: z.boolean().describe("Include archived tasks when no status filter is provided").default(false),
  },
  async (params) => {
    try {
      const tasks = await client.listTasks(params.team_id, {
        status: params.status,
        assignee_id: params.assignee_id,
        include_archived: params.include_archived,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(tasks, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_task",
  "Get detailed info about a single task.",
  { task_id: z.number().describe("Task ID") },
  async (params) => {
    try {
      const task = await client.getTask(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "update_task",
  "Update task fields (title, description, priority, tags). Does NOT change status.",
  {
    task_id: z.number().describe("Task ID"),
    title: z.string().describe("New title").optional(),
    description: z.string().describe("New description").optional(),
    priority: z.enum(["low", "medium", "high", "critical"]).describe("New priority").optional(),
    tags: z.array(z.string()).describe("New tags").optional(),
  },
  async (params) => {
    try {
      const task = await client.updateTask(params.task_id, {
        title: params.title,
        description: params.description,
        priority: params.priority,
        tags: params.tags,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "change_task_status",
  "Change task status. Validates transitions (can't skip steps) and enforces DAG dependencies.",
  {
    task_id: z.number().describe("Task ID"),
    status: z.enum(["todo", "in_progress", "in_review", "in_approval", "merging", "done", "cancelled", "archived"]).describe("New status"),
    actor_id: z.string().describe("UUID of the agent/user making the change").optional(),
  },
  async (params) => {
    try {
      const task = await client.changeTaskStatus(params.task_id, params.status, params.actor_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "archive_task",
  "Archive a task that is already done or cancelled.",
  {
    task_id: z.number().describe("Task ID"),
    actor_id: z.string().describe("UUID of the agent/user making the change").optional(),
  },
  async (params) => {
    try {
      const task = await client.archiveTask(params.task_id, params.actor_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "assign_task",
  "Assign an agent to work on a task.",
  {
    task_id: z.number().describe("Task ID"),
    assignee_id: z.string().describe("Agent UUID to assign"),
  },
  async (params) => {
    try {
      const task = await client.assignTask(params.task_id, params.assignee_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_task_events",
  "Get the event history for a task — immutable audit trail of all changes.",
  { task_id: z.number().describe("Task ID") },
  async (params) => {
    try {
      const events = await client.getTaskEvents(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(events, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_dependent_tasks",
  "Get the list of tasks that depend on this task (dependent tasks). Shows task IDs, titles, and current status.",
  { task_id: z.number().describe("Task ID") },
  async (params) => {
    try {
      const dependentTasks = await client.getDependentTasks(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(dependentTasks, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ─── Messages ───────────────────────────────────────────────

server.tool(
  "send_message",
  "Send a message to an agent or user. Used for inter-agent communication.",
  {
    team_id: z.string().describe("Team UUID"),
    sender_id: z.string().describe("Sender UUID"),
    sender_type: z.enum(["agent", "user"]).describe("Sender type"),
    recipient_id: z.string().describe("Recipient UUID"),
    recipient_type: z.enum(["agent", "user"]).describe("Recipient type"),
    content: z.string().describe("Message content"),
    task_id: z.number().describe("Related task ID").optional(),
  },
  async (params) => {
    try {
      const msg = await client.sendMessage(
        params.team_id,
        params.sender_id,
        params.sender_type,
        params.recipient_id,
        params.recipient_type,
        params.content,
        params.task_id
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(msg, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_inbox",
  "Get an agent's inbox — unprocessed messages waiting for them.",
  {
    agent_id: z.string().describe("Agent UUID"),
    unprocessed_only: z.boolean().describe("Only return unprocessed messages").default(true),
  },
  async (params) => {
    try {
      const messages = await client.getInbox(params.agent_id, {
        unprocessed_only: params.unprocessed_only,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(messages, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 3: Git — Worktrees, Diffs, Files
// ═══════════════════════════════════════════════════════════

server.tool(
  "create_worktree",
  "Create a git worktree for a task. Each task gets its own branch and isolated checkout.",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
  },
  async (params) => {
    try {
      const info = await client.createWorktree(params.task_id, params.repo_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(info, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_worktree",
  "Get info about a task's git worktree (path, branch, exists).",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
  },
  async (params) => {
    try {
      const info = await client.getWorktreeInfo(params.task_id, params.repo_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(info, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "remove_worktree",
  "Remove a task's git worktree (after merge or cancellation).",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
  },
  async (params) => {
    try {
      const result = await client.removeWorktree(params.task_id, params.repo_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_task_diff",
  "Get the full git diff of a task's branch vs the default branch.",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
  },
  async (params) => {
    try {
      const result = await client.getTaskDiff(params.task_id, params.repo_id);
      return {
        content: [{ type: "text" as const, text: result.diff || "(no changes)" }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_changed_files",
  "List files changed on a task's branch (with additions/deletions count).",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
  },
  async (params) => {
    try {
      const files = await client.getChangedFiles(params.task_id, params.repo_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(files, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "read_file",
  "Read a file from a task's branch (without needing the worktree checked out).",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
    path: z.string().describe("File path relative to repo root"),
  },
  async (params) => {
    try {
      const result = await client.getFileContent(params.task_id, params.repo_id, params.path);
      return {
        content: [{ type: "text" as const, text: result.content }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_commits",
  "Get the commit log for a task's branch (commits not on the default branch).",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
    limit: z.number().describe("Max commits to return").default(20),
  },
  async (params) => {
    try {
      const commits = await client.getCommitLog(params.task_id, params.repo_id, params.limit);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(commits, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 4: Sessions / Cost Controls
// ═══════════════════════════════════════════════════════════

server.tool(
  "start_session",
  "Start a new agent work session. Checks budget limits first — returns 429 if over budget.",
  {
    agent_id: z.string().describe("Agent UUID"),
    task_id: z.number().describe("Task ID being worked on").optional(),
    model: z.string().describe("Override model for this session").optional(),
  },
  async (params) => {
    try {
      const session = await client.startSession(
        params.agent_id,
        params.task_id,
        params.model
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(session, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "record_usage",
  "Record token usage for an active session. Updates running cost totals.",
  {
    session_id: z.number().describe("Session ID"),
    tokens_in: z.number().describe("Input tokens used").default(0),
    tokens_out: z.number().describe("Output tokens used").default(0),
    cache_read: z.number().describe("Cache tokens read").default(0),
    cache_write: z.number().describe("Cache tokens written").default(0),
  },
  async (params) => {
    try {
      const session = await client.recordUsage(
        params.session_id,
        params.tokens_in,
        params.tokens_out,
        params.cache_read,
        params.cache_write
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(session, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "end_session",
  "End an agent work session. Records final state and sets agent back to idle.",
  {
    session_id: z.number().describe("Session ID"),
    error: z.string().describe("Error message if session failed").optional(),
  },
  async (params) => {
    try {
      const session = await client.endSession(params.session_id, params.error);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(session, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "check_budget",
  "Check if an agent has budget remaining (daily and per-task limits).",
  {
    agent_id: z.string().describe("Agent UUID"),
    task_id: z.number().describe("Task ID to check task-level budget").optional(),
  },
  async (params) => {
    try {
      const status = await client.checkBudget(params.agent_id, params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(status, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_cost_summary",
  "Get cost summary for a team — per-agent and per-model breakdown over a period.",
  {
    team_id: z.string().describe("Team UUID"),
    days: z.number().describe("Number of days to look back").default(7),
  },
  async (params) => {
    try {
      const summary = await client.getCostSummary(params.team_id, params.days);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(summary, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 7: Human-in-the-Loop
// ═══════════════════════════════════════════════════════════

server.tool(
  "ask_human",
  "Ask a human for input — question, approval, or review. Creates a persistent request that appears in the dashboard. Use wait=true to block until the human responds.",
  {
    team_id: z.string().describe("Team UUID"),
    agent_id: z.string().describe("Agent UUID making the request"),
    kind: z.enum(["question", "approval", "review"]).describe("Request type"),
    question: z.string().describe("The question or request text"),
    task_id: z.number().describe("Related task ID").optional(),
    options: z.array(z.string()).describe("Pre-defined answer options (e.g. ['approve', 'reject'])").default([]),
    timeout_minutes: z.number().describe("Auto-expire after N minutes").optional(),
    wait: z.boolean().describe("If true, block until the human responds (polls every 5s). Use this when running as a subprocess via an adapter.").default(false),
  },
  async (params) => {
    try {
      const hr = await client.createHumanRequest(
        params.team_id,
        params.agent_id,
        params.kind,
        params.question,
        {
          task_id: params.task_id,
          options: params.options,
          timeout_minutes: params.timeout_minutes,
        }
      );

      // If wait=true, poll until the human responds
      if (params.wait) {
        const resolved = await client.pollForResponse(hr.id);
        return {
          content: [{ type: "text" as const, text: JSON.stringify(resolved, null, 2) }],
        };
      }

      // Non-blocking: return immediately with pending status
      return {
        content: [{ type: "text" as const, text: JSON.stringify(hr, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_pending_requests",
  "Get pending human requests for a team — requests waiting for human response.",
  {
    team_id: z.string().describe("Team UUID"),
    agent_id: z.string().describe("Filter by agent UUID").optional(),
    task_id: z.number().describe("Filter by task ID").optional(),
  },
  async (params) => {
    try {
      const requests = await client.listHumanRequests(params.team_id, {
        status: "pending",
        agent_id: params.agent_id,
        task_id: params.task_id,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(requests, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "respond_to_request",
  "Respond to a pending human request. Used by humans (or automated systems) to answer agent questions.",
  {
    request_id: z.number().describe("Human request ID"),
    response: z.string().describe("The response text"),
    responded_by: z.string().describe("User UUID who is responding").optional(),
  },
  async (params) => {
    try {
      const hr = await client.respondToHumanRequest(
        params.request_id,
        params.response,
        params.responded_by
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(hr, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 8: Code Review + Merge
// ═══════════════════════════════════════════════════════════

server.tool(
  "request_review",
  "Request a code review for a task. Creates a new review attempt.",
  {
    task_id: z.number().describe("Task ID to review"),
    reviewer_id: z.string().describe("Reviewer UUID (user or agent)").optional(),
    reviewer_type: z.enum(["user", "agent"]).describe("Reviewer type").default("user"),
  },
  async (params) => {
    try {
      const review = await client.requestReview(params.task_id, {
        reviewer_id: params.reviewer_id,
        reviewer_type: params.reviewer_type,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(review, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "approve_task",
  "Approve the latest review for a task. Marks it ready for merge.",
  {
    task_id: z.number().describe("Task ID to approve"),
    summary: z.string().describe("Approval summary/notes").optional(),
    reviewer_id: z.string().describe("Reviewer UUID").optional(),
  },
  async (params) => {
    try {
      const review = await client.approveTask(params.task_id, {
        summary: params.summary,
        reviewer_id: params.reviewer_id,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(review, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "reject_task",
  "Reject the latest review for a task. Sends it back for more work.",
  {
    task_id: z.number().describe("Task ID to reject"),
    summary: z.string().describe("Rejection reason/feedback").optional(),
    reviewer_id: z.string().describe("Reviewer UUID").optional(),
  },
  async (params) => {
    try {
      const review = await client.rejectTask(params.task_id, {
        summary: params.summary,
        reviewer_id: params.reviewer_id,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(review, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_merge_status",
  "Get the merge readiness status for a task — review verdict, merge jobs, can_merge flag.",
  {
    task_id: z.number().describe("Task ID"),
  },
  async (params) => {
    try {
      const status = await client.getMergeStatus(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(status, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_review_feedback",
  "Get the latest review feedback for a task — comments, verdict, and summary from the most recent request_changes review. Use this to understand what the reviewer wants you to fix.",
  {
    task_id: z.number().describe("Task ID"),
  },
  async (params) => {
    try {
      const feedback = await client.getReviewFeedback(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(feedback, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 9: Authentication
// ═══════════════════════════════════════════════════════════

server.tool(
  "authenticate",
  "Validate an API key and return the scoped identity (org, permissions). Use this to verify API key credentials.",
  {
    api_key: z.string().describe("The API key to validate (e.g. oc_...)"),
  },
  async (params) => {
    try {
      const identity = await client.authenticate(params.api_key);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(identity, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 10: Webhooks + Settings
// ═══════════════════════════════════════════════════════════

server.tool(
  "create_webhook",
  "Create a webhook to receive events from GitHub/GitLab. Returns the webhook with its auto-generated secret.",
  {
    org_id: z.string().describe("Organization UUID"),
    name: z.string().describe("Webhook name"),
    team_id: z.string().describe("Scope to a specific team (optional)").optional(),
    provider: z.enum(["github", "gitlab", "bitbucket", "custom"]).describe("Webhook provider").default("github"),
    events: z.array(z.string()).describe("Event types to listen for").default(["push", "pull_request"]),
  },
  async (params) => {
    try {
      const webhook = await client.createWebhook(params.org_id, params.name, {
        team_id: params.team_id,
        provider: params.provider,
        events: params.events,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(webhook, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "list_webhooks",
  "List webhooks for an organization.",
  {
    org_id: z.string().describe("Organization UUID"),
    team_id: z.string().describe("Filter by team UUID").optional(),
    active_only: z.boolean().describe("Only show active webhooks").default(false),
  },
  async (params) => {
    try {
      const webhooks = await client.listWebhooks(params.org_id, {
        team_id: params.team_id,
        active_only: params.active_only,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(webhooks, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "update_webhook",
  "Update a webhook configuration — name, events, active status.",
  {
    webhook_id: z.string().describe("Webhook UUID"),
    name: z.string().describe("New name").optional(),
    events: z.array(z.string()).describe("New event types").optional(),
    active: z.boolean().describe("Enable/disable the webhook").optional(),
  },
  async (params) => {
    try {
      const webhook = await client.updateWebhook(params.webhook_id, {
        name: params.name,
        events: params.events,
        active: params.active,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(webhook, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_team_settings",
  "Get team-level configuration — budget limits, model preferences, workflow settings.",
  {
    team_id: z.string().describe("Team UUID"),
  },
  async (params) => {
    try {
      const settings = await client.getTeamSettings(params.team_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(settings, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "update_team_settings",
  "Update team configuration — budget limits, default model, auto-merge, etc.",
  {
    team_id: z.string().describe("Team UUID"),
    daily_cost_limit_usd: z.number().describe("Daily cost limit in USD").optional(),
    task_cost_limit_usd: z.number().describe("Per-task cost limit in USD").optional(),
    default_model: z.string().describe("Default model for new sessions").optional(),
    auto_merge: z.boolean().describe("Auto-merge after approval").optional(),
    require_review: z.boolean().describe("Require review before merge").optional(),
    branch_prefix: z.string().describe("Branch naming prefix").optional(),
  },
  async (params) => {
    try {
      const { team_id, ...settings } = params;
      // Remove undefined values
      const cleanSettings: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(settings)) {
        if (value !== undefined) cleanSettings[key] = value;
      }
      const result = await client.updateTeamSettings(team_id, cleanSettings);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_team_conventions",
  "Get team coding conventions — standards, architecture decisions, testing strategies. These are injected into agent prompts automatically.",
  {
    team_id: z.string().describe("Team UUID"),
  },
  async (params) => {
    try {
      const conventions = await client.getTeamConventions(params.team_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(conventions, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "add_team_convention",
  "Record a new team convention — coding standard, architecture decision, or workflow preference. Agents will follow this in future runs.",
  {
    team_id: z.string().describe("Team UUID"),
    key: z.string().describe("Convention identifier (e.g. 'testing', 'code_style', 'architecture')"),
    content: z.string().describe("The convention text — what agents should follow"),
    active: z.boolean().describe("Whether the convention is active").default(true),
  },
  async (params) => {
    try {
      const convention = await client.addTeamConvention(
        params.team_id,
        params.key,
        params.content,
        params.active
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(convention, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 16: Multi-Agent Orchestration
// ═══════════════════════════════════════════════════════════

server.tool(
  "wait_for_task_completion",
  "Block until a task reaches a terminal status (done, cancelled, archived, or in_review). Use this as a manager agent to wait for an engineer to finish a task.",
  {
    task_id: z.number().describe("Task ID to wait for"),
    timeout_seconds: z.number().describe("Max seconds to wait (default 3600 = 1 hour)").default(3600),
    terminal_statuses: z.array(z.string()).describe("Statuses to consider terminal").default(["done", "cancelled", "archived", "in_review"]),
  },
  async (params) => {
    try {
      const task = await client.pollForTaskCompletion(
        params.task_id,
        10000, // poll every 10 seconds
        params.timeout_seconds * 1000,
        params.terminal_statuses
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(task, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "create_tasks_batch",
  "Create multiple tasks at once. Supports inter-batch dependencies via depends_on_indices (0-based positions in the batch). Use this as a manager agent to break down work into parallel or sequential engineer tasks.",
  {
    team_id: z.string().describe("Team UUID"),
    tasks: z.array(z.object({
      title: z.string().describe("Task title"),
      description: z.string().describe("Task description").default(""),
      priority: z.enum(["low", "medium", "high", "critical"]).default("medium"),
      assignee_id: z.string().describe("Agent UUID to assign").optional(),
      depends_on_indices: z.array(z.number()).describe("Indices (0-based) of other tasks in this batch that this task depends on").default([]),
      tags: z.array(z.string()).default([]),
    })).describe("Array of tasks to create"),
  },
  async (params) => {
    try {
      const tasks = await client.createTasksBatch(params.team_id, params.tasks);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(tasks, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "list_team_agents",
  "List all agents in a team with their roles and current status. Alias for list_agents — useful for manager agents to check team capacity before delegating work.",
  {
    team_id: z.string().describe("Team UUID"),
  },
  async (params) => {
    try {
      const agents = await client.listAgents(params.team_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(agents, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Tier 1: Git Push + PR Creation
// ═══════════════════════════════════════════════════════════

server.tool(
  "push_branch",
  "Push a task's git branch to the remote. Used before creating a PR or when you want to share your work.",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
    remote: z.string().describe("Remote name (default: origin)").default("origin"),
    force: z.boolean().describe("Force push with --force-with-lease").default(false),
  },
  async (params) => {
    try {
      const result = await client.pushBranch(params.task_id, params.repo_id, {
        remote: params.remote,
        force: params.force,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "create_pr",
  "Create a GitHub pull request for a task's branch. Uses the `gh` CLI under the hood.",
  {
    task_id: z.number().describe("Task ID"),
    repo_id: z.string().describe("Repository UUID"),
    title: z.string().describe("PR title (defaults to task title)").optional(),
    body: z.string().describe("PR body/description").optional(),
    draft: z.boolean().describe("Create as draft PR").default(false),
    base_branch: z.string().describe("Base branch (defaults to repo default)").optional(),
  },
  async (params) => {
    try {
      const result = await client.createPR(params.task_id, params.repo_id, {
        title: params.title,
        body: params.body,
        draft: params.draft,
        base_branch: params.base_branch,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_pr_info",
  "Get PR information (URL, number) for a task from stored metadata.",
  {
    task_id: z.number().describe("Task ID"),
  },
  async (params) => {
    try {
      const result = await client.getPRInfo(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Tier 1: Agent Code Review
// ═══════════════════════════════════════════════════════════

server.tool(
  "submit_review_verdict",
  "Submit a verdict on a code review: approve, request_changes, or reject. Used by reviewer agents after reading diffs and leaving comments.",
  {
    review_id: z.number().describe("Review ID"),
    verdict: z.enum(["approve", "request_changes", "reject"]).describe("The review verdict"),
    summary: z.string().describe("Summary of the review").optional(),
    reviewer_id: z.string().describe("Reviewer agent UUID").optional(),
    reviewer_type: z.string().describe("Reviewer type (agent or user)").default("agent"),
  },
  async (params) => {
    try {
      const result = await client.submitReviewVerdict(params.review_id, params.verdict, {
        summary: params.summary,
        reviewer_id: params.reviewer_id,
        reviewer_type: params.reviewer_type,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "add_review_comment",
  "Add a comment to a code review — optionally anchored to a specific file and line number. Used by reviewer agents to leave inline feedback.",
  {
    review_id: z.number().describe("Review ID"),
    author_id: z.string().describe("Author (reviewer agent) UUID"),
    author_type: z.string().describe("Author type (agent or user)").default("agent"),
    content: z.string().describe("Comment content — explain the issue and suggest a fix"),
    file_path: z.string().describe("File path (e.g. 'src/foo.py')").optional(),
    line_number: z.number().describe("Line number in the file").optional(),
  },
  async (params) => {
    try {
      const result = await client.addReviewComment(params.review_id, {
        author_id: params.author_id,
        author_type: params.author_type,
        content: params.content,
        file_path: params.file_path,
        line_number: params.line_number,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Tier 1: Context Carryover
// ═══════════════════════════════════════════════════════════

server.tool(
  "save_context",
  "Save a key-value discovery to the task's persistent context. Persists across agent runs so you don't lose findings between turns. Use for root causes, architecture decisions, key files, etc.",
  {
    task_id: z.number().describe("Task ID"),
    key: z.string().describe("Context key (e.g. 'root_cause', 'key_files', 'architecture_decision')"),
    value: z.string().describe("Context value — what you discovered"),
  },
  async (params) => {
    try {
      const result = await client.saveContext(params.task_id, params.key, params.value);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_context",
  "Get all saved context for a task — previous discoveries, decisions, and findings from earlier runs.",
  {
    task_id: z.number().describe("Task ID"),
  },
  async (params) => {
    try {
      const result = await client.getContext(params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 12: Runs
// ═══════════════════════════════════════════════════════════

server.tool(
  "create_run",
  "Create a new run — a top-level orchestration unit that decomposes a human intent into a task graph, gets approval, and executes tasks automatically via AI agents.",
  {
    team_id: z.string().describe("Team UUID"),
    title: z.string().describe("Short title for the run"),
    intent: z.string().describe("Human intent — what should be built. Be specific and detailed."),
    budget_limit_usd: z.number().describe("Maximum budget in USD (default: 10.0)").default(10.0),
    repository_id: z.string().describe("Repository UUID (optional)").optional(),
  },
  async (params) => {
    try {
      const run = await client.createRun(params.team_id, params.title, params.intent, {
        budget_limit_usd: params.budget_limit_usd,
        repository_id: params.repository_id,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "list_runs",
  "List runs for a team, optionally filtered by status.",
  {
    team_id: z.string().describe("Team UUID"),
    status: z.string().describe("Filter by status (draft, planning, executing, done, failed, etc.)").optional(),
  },
  async (params) => {
    try {
      const runs = await client.listRuns(params.team_id, {
        status: params.status,
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(runs, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_run",
  "Get detailed information about a run including its status, task graph, and budget.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const run = await client.getRun(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "set_run_task_graph",
  "Set the task graph for a run — creates RunTask rows from a structured task list. Use this as a manager agent to submit your decomposition plan. The run must be in 'draft' or 'planning' status. After setting the task graph, transition the run to 'awaiting_plan_approval'.",
  {
    run_id: z.string().describe("Run UUID"),
    tasks: z.array(z.object({
      title: z.string().describe("Short task title"),
      description: z.string().describe("Detailed description including specific files, patterns, and acceptance criteria"),
      complexity: z.enum(["S", "M", "L", "XL"]).describe("S: <30min, M: 30-90min, L: 90-180min, XL: 180+min"),
      assigned_role: z.enum(["engineer", "reviewer"]).default("engineer"),
      dependencies: z.array(z.number()).describe("Zero-indexed IDs of tasks that must complete before this one").default([]),
      integration_hints: z.array(z.string()).describe("How this task's output connects to other tasks").default([]),
    })).describe("Array of tasks forming the task graph"),
  },
  async (params) => {
    try {
      const taskGraph = { tasks: params.tasks };
      const run = await client.setRunTaskGraph(params.run_id, taskGraph);
      return {
        content: [{ type: "text" as const, text: `Task graph set with ${params.tasks.length} tasks.\n\n${JSON.stringify(run, null, 2)}` }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "start_run",
  "Start planning for a run — kicks off the LLM planner to decompose the intent into a task graph. Run must be in 'draft' status.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const run = await client.startRun(params.run_id);
      return {
        content: [{ type: "text" as const, text: `Run planning started. Status will transition to 'awaiting_plan_approval' when the plan is ready.\n\n${JSON.stringify(run, null, 2)}` }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_run_tasks",
  "List all tasks in a run's task graph with their status, dependencies, and assigned agents.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const tasks = await client.getRunTasks(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(tasks, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "approve_run_plan",
  "Approve a run's generated plan — starts automated execution of all tasks in the task graph. Run must be in 'awaiting_plan_approval' status.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const run = await client.approveRunPlan(params.run_id);
      return {
        content: [{ type: "text" as const, text: `Plan approved! Execution started.\n\n${JSON.stringify(run, null, 2)}` }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "reject_run_plan",
  "Reject a run's generated plan with optional feedback. The run returns to draft status so it can be re-planned.",
  {
    run_id: z.string().describe("Run UUID"),
    feedback: z.string().describe("Feedback explaining why the plan was rejected and what to change").optional(),
  },
  async (params) => {
    try {
      const run = await client.rejectRunPlan(params.run_id, {
        feedback: params.feedback,
      });
      return {
        content: [{ type: "text" as const, text: `Plan rejected. Run returned to draft.\n\n${JSON.stringify(run, null, 2)}` }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "pause_run",
  "Pause an executing run. Running tasks will complete but no new tasks will start.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const run = await client.pauseRun(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "resume_run",
  "Resume a paused run — continues executing tasks from where it left off.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const run = await client.resumeRun(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_run_budget",
  "Get the budget ledger for a run — shows spent vs. limit and budget status.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const budget = await client.getRunBudget(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(budget, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ─── Phase 2A: Contracts ────────────────────────────────────

server.tool(
  "list_run_contracts",
  "List all interface contracts for a run — shows contract types, specs, and lock status.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const contracts = await client.listContracts(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(contracts, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "get_run_contract",
  "Get a specific contract by ID with full specification details.",
  {
    run_id: z.string().describe("Run UUID"),
    contract_id: z.number().describe("Contract ID (integer)"),
  },
  async (params) => {
    try {
      const contract = await client.getContract(params.run_id, params.contract_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(contract, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "lock_run_contract",
  "Agent acknowledges a contract before starting work — locks the contract to the agent.",
  {
    run_id: z.string().describe("Run UUID"),
    contract_id: z.number().describe("Contract ID (integer)"),
    agent_id: z.string().describe("Agent UUID that is acknowledging the contract"),
  },
  async (params) => {
    try {
      const contract = await client.lockContract(params.run_id, params.contract_id, params.agent_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(contract, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "generate_run_contracts",
  "Trigger contract generation from the task graph — analyzes inter-task boundaries and generates typed interface contracts.",
  {
    run_id: z.string().describe("Run UUID"),
  },
  async (params) => {
    try {
      const run = await client.generateContracts(params.run_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ═══════════════════════════════════════════════════════════
// Phase 3B: Sandbox
// ═══════════════════════════════════════════════════════════

server.tool(
  "list_sandbox_runs",
  "List sandbox test runs for a run task — shows pass/fail status, stdout/stderr, and duration.",
  {
    run_id: z.string().describe("Run UUID"),
    task_id: z.number().describe("Run task ID"),
  },
  async (params) => {
    try {
      const runs = await client.listSandboxRuns(params.run_id, params.task_id);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(runs, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "trigger_sandbox_run",
  "Trigger a Docker-based sandbox test run for a run task. Returns 202 — the test runs asynchronously.",
  {
    run_id: z.string().describe("Run UUID"),
    task_id: z.number().describe("Run task ID"),
    test_cmd: z.string().describe("Shell command to run tests (e.g., 'pytest tests/')"),
    image: z.string().optional().describe("Docker image (default: python:3.12-slim)"),
    setup_cmd: z.string().optional().describe("Optional setup command to run before tests"),
    timeout: z.number().optional().describe("Timeout in seconds (default: 300)"),
  },
  async (params) => {
    try {
      const run = await client.triggerSandboxRun(
        params.run_id,
        params.task_id,
        params.test_cmd,
        {
          image: params.image,
          setup_cmd: params.setup_cmd,
          timeout: params.timeout,
        }
      );
      return {
        content: [{ type: "text" as const, text: JSON.stringify(run, null, 2) }],
      };
    } catch (error) {
      return {
        content: [{ type: "text" as const, text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
        isError: true,
      };
    }
  }
);

// ─── Start server ──────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((error) => {
  console.error("MCP server error:", error);
  process.exit(1);
});
