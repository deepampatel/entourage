/**
 * HTTP client for the OpenClaw backend API.
 *
 * Learn: This is the bridge between MCP tools and our REST API.
 * Every MCP tool calls a method here, which makes an HTTP request
 * to the backend. Clean separation of protocol (MCP) from transport (HTTP).
 *
 * Grows with each phase as new API endpoints are added.
 */

const API_URL = process.env.OPENCLAW_API_URL || "http://localhost:8000";

interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string>;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = new URL(path, API_URL);

  if (opts.params) {
    for (const [key, value] of Object.entries(opts.params)) {
      url.searchParams.set(key, value);
    }
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // API key auth — pass via X-API-Key header if configured
  if (process.env.OPENCLAW_API_KEY) {
    headers["X-API-Key"] = process.env.OPENCLAW_API_KEY;
  }

  const resp = await fetch(url.toString(), {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  if (!resp.ok) {
    const error = await resp.text();
    throw new Error(`API error ${resp.status}: ${error}`);
  }

  return resp.json() as Promise<T>;
}

// ─── Phase 0: Health ───────────────────────────────────────

export async function ping(): Promise<Record<string, unknown>> {
  return request("/api/v1/health");
}

// ─── Phase 1: Teams / Agents / Repos ───────────────────────

export interface Org {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Team {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface TeamDetail extends Team {
  agents: Agent[];
  repositories: Repo[];
}

export interface Agent {
  id: string;
  team_id: string;
  name: string;
  role: string;
  model: string;
  config: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface Repo {
  id: string;
  team_id: string;
  name: string;
  local_path: string;
  default_branch: string;
  config: Record<string, unknown>;
  created_at: string;
}

export async function listOrgs(): Promise<Org[]> {
  return request("/api/v1/orgs");
}

export async function createOrg(name: string, slug: string): Promise<Org> {
  return request("/api/v1/orgs", { method: "POST", body: { name, slug } });
}

export async function listTeams(orgId: string): Promise<Team[]> {
  return request(`/api/v1/orgs/${orgId}/teams`);
}

export async function createTeam(
  orgId: string,
  name: string,
  slug: string
): Promise<Team> {
  return request(`/api/v1/orgs/${orgId}/teams`, {
    method: "POST",
    body: { name, slug },
  });
}

export async function getTeam(teamId: string): Promise<TeamDetail> {
  return request(`/api/v1/teams/${teamId}`);
}

export async function listAgents(teamId: string): Promise<Agent[]> {
  return request(`/api/v1/teams/${teamId}/agents`);
}

export async function createAgent(
  teamId: string,
  name: string,
  role: string = "engineer",
  model: string = "claude-sonnet-4-20250514",
  config: Record<string, unknown> = {}
): Promise<Agent> {
  return request(`/api/v1/teams/${teamId}/agents`, {
    method: "POST",
    body: { name, role, model, config },
  });
}

export async function listRepos(teamId: string): Promise<Repo[]> {
  return request(`/api/v1/teams/${teamId}/repos`);
}

export async function registerRepo(
  teamId: string,
  name: string,
  localPath: string,
  defaultBranch: string = "main",
  config: Record<string, unknown> = {}
): Promise<Repo> {
  return request(`/api/v1/teams/${teamId}/repos`, {
    method: "POST",
    body: { name, local_path: localPath, default_branch: defaultBranch, config },
  });
}

// ─── Phase 2: Tasks / Messages ─────────────────────────────

export interface Task {
  id: number;
  team_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  dri_id: string | null;
  assignee_id: string | null;
  depends_on: number[];
  repo_ids: string[];
  tags: string[];
  branch: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskEvent {
  id: number;
  type: string;
  data: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Msg {
  id: number;
  team_id: string;
  sender_id: string;
  sender_type: string;
  recipient_id: string;
  recipient_type: string;
  task_id: number | null;
  content: string;
  created_at: string;
}

export async function createTask(
  teamId: string,
  title: string,
  opts: {
    description?: string;
    priority?: string;
    assignee_id?: string;
    dri_id?: string;
    depends_on?: number[];
    repo_ids?: string[];
    tags?: string[];
  } = {}
): Promise<Task> {
  return request(`/api/v1/teams/${teamId}/tasks`, {
    method: "POST",
    body: { title, ...opts },
  });
}

export async function listTasks(
  teamId: string,
  opts: { status?: string; assignee_id?: string; limit?: number } = {}
): Promise<Task[]> {
  const params: Record<string, string> = {};
  if (opts.status) params.status = opts.status;
  if (opts.assignee_id) params.assignee_id = opts.assignee_id;
  if (opts.limit) params.limit = String(opts.limit);
  return request(`/api/v1/teams/${teamId}/tasks`, { params });
}

export async function getTask(taskId: number): Promise<Task> {
  return request(`/api/v1/tasks/${taskId}`);
}

export async function updateTask(
  taskId: number,
  updates: { title?: string; description?: string; priority?: string; tags?: string[] }
): Promise<Task> {
  return request(`/api/v1/tasks/${taskId}`, {
    method: "PATCH",
    body: updates,
  });
}

export async function changeTaskStatus(
  taskId: number,
  status: string,
  actorId?: string
): Promise<Task> {
  return request(`/api/v1/tasks/${taskId}/status`, {
    method: "POST",
    body: { status, actor_id: actorId },
  });
}

export async function assignTask(
  taskId: number,
  assigneeId: string
): Promise<Task> {
  return request(`/api/v1/tasks/${taskId}/assign`, {
    method: "POST",
    body: { assignee_id: assigneeId },
  });
}

export async function getTaskEvents(taskId: number): Promise<TaskEvent[]> {
  return request(`/api/v1/tasks/${taskId}/events`);
}

export async function sendMessage(
  teamId: string,
  senderId: string,
  senderType: string,
  recipientId: string,
  recipientType: string,
  content: string,
  taskId?: number
): Promise<Msg> {
  return request(`/api/v1/teams/${teamId}/messages`, {
    method: "POST",
    body: {
      sender_id: senderId,
      sender_type: senderType,
      recipient_id: recipientId,
      recipient_type: recipientType,
      content,
      task_id: taskId,
    },
  });
}

export async function getInbox(
  agentId: string,
  opts: { unprocessed_only?: boolean; limit?: number } = {}
): Promise<Msg[]> {
  const params: Record<string, string> = {};
  if (opts.unprocessed_only !== undefined)
    params.unprocessed_only = String(opts.unprocessed_only);
  if (opts.limit) params.limit = String(opts.limit);
  return request(`/api/v1/agents/${agentId}/inbox`, { params });
}

// ─── Phase 3: Git ──────────────────────────────────────────

export interface WorktreeInfo {
  path: string;
  branch: string;
  exists: boolean;
  repo_path: string;
  repo_name: string;
}

export interface DiffFile {
  path: string;
  status: string;
  additions: number;
  deletions: number;
}

export interface Commit {
  hash: string;
  author_name: string;
  author_email: string;
  message: string;
  date: string;
}

export async function createWorktree(taskId: number, repoId: string): Promise<WorktreeInfo> {
  return request(`/api/v1/tasks/${taskId}/worktree`, {
    method: "POST",
    params: { repo_id: repoId },
  });
}

export async function removeWorktree(taskId: number, repoId: string): Promise<{ removed: boolean }> {
  return request(`/api/v1/tasks/${taskId}/worktree`, {
    method: "DELETE",
    params: { repo_id: repoId },
  });
}

export async function getWorktreeInfo(taskId: number, repoId: string): Promise<WorktreeInfo> {
  return request(`/api/v1/tasks/${taskId}/worktree`, {
    params: { repo_id: repoId },
  });
}

export async function getTaskDiff(taskId: number, repoId: string): Promise<{ diff: string }> {
  return request(`/api/v1/tasks/${taskId}/diff`, {
    params: { repo_id: repoId },
  });
}

export async function getChangedFiles(taskId: number, repoId: string): Promise<DiffFile[]> {
  return request(`/api/v1/tasks/${taskId}/files`, {
    params: { repo_id: repoId },
  });
}

export async function getFileContent(
  taskId: number,
  repoId: string,
  filePath: string
): Promise<{ path: string; content: string }> {
  return request(`/api/v1/tasks/${taskId}/file`, {
    params: { repo_id: repoId, path: filePath },
  });
}

export async function getCommitLog(
  taskId: number,
  repoId: string,
  limit: number = 20
): Promise<Commit[]> {
  return request(`/api/v1/tasks/${taskId}/commits`, {
    params: { repo_id: repoId, limit: String(limit) },
  });
}

// ─── Phase 4: Sessions / Costs ──────────────────────────────

export interface SessionInfo {
  id: number;
  agent_id: string;
  task_id: number | null;
  started_at: string;
  ended_at: string | null;
  tokens_in: number;
  tokens_out: number;
  cache_read: number;
  cache_write: number;
  cost_usd: number;
  model: string | null;
  error: string | null;
}

export interface BudgetStatus {
  within_budget: boolean;
  daily_spent_usd: number;
  daily_limit_usd: number;
  task_spent_usd: number;
  task_limit_usd: number;
  violations: string[];
}

export interface CostSummary {
  team_id: string;
  period_days: number;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  session_count: number;
  per_agent: { agent_id: string; agent_name: string; cost_usd: number; sessions: number }[];
  per_model: { model: string | null; cost_usd: number; sessions: number }[];
}

export async function startSession(
  agentId: string,
  taskId?: number,
  model?: string
): Promise<SessionInfo> {
  return request("/api/v1/sessions/start", {
    method: "POST",
    body: { agent_id: agentId, task_id: taskId, model },
  });
}

export async function recordUsage(
  sessionId: number,
  tokensIn: number = 0,
  tokensOut: number = 0,
  cacheRead: number = 0,
  cacheWrite: number = 0
): Promise<SessionInfo> {
  return request(`/api/v1/sessions/${sessionId}/usage`, {
    method: "POST",
    body: {
      tokens_in: tokensIn,
      tokens_out: tokensOut,
      cache_read: cacheRead,
      cache_write: cacheWrite,
    },
  });
}

export async function endSession(
  sessionId: number,
  error?: string
): Promise<SessionInfo> {
  return request(`/api/v1/sessions/${sessionId}/end`, {
    method: "POST",
    body: { error },
  });
}

export async function getSession(sessionId: number): Promise<SessionInfo> {
  return request(`/api/v1/sessions/${sessionId}`);
}

export async function listSessions(
  agentId: string,
  opts: { task_id?: number; limit?: number } = {}
): Promise<SessionInfo[]> {
  const params: Record<string, string> = {};
  if (opts.task_id) params.task_id = String(opts.task_id);
  if (opts.limit) params.limit = String(opts.limit);
  return request(`/api/v1/agents/${agentId}/sessions`, { params });
}

export async function checkBudget(
  agentId: string,
  taskId?: number
): Promise<BudgetStatus> {
  const params: Record<string, string> = {};
  if (taskId) params.task_id = String(taskId);
  return request(`/api/v1/agents/${agentId}/budget`, { params });
}

export async function getCostSummary(
  teamId: string,
  days: number = 7
): Promise<CostSummary> {
  return request(`/api/v1/teams/${teamId}/costs`, {
    params: { days: String(days) },
  });
}

// ─── Phase 7: Human-in-the-loop ─────────────────────────

export interface HumanRequestInfo {
  id: number;
  team_id: string;
  agent_id: string;
  task_id: number | null;
  kind: string;
  question: string;
  options: string[];
  status: string;
  response: string | null;
  responded_by: string | null;
  timeout_at: string | null;
  created_at: string;
  resolved_at: string | null;
}

export async function createHumanRequest(
  teamId: string,
  agentId: string,
  kind: string,
  question: string,
  opts: {
    task_id?: number;
    options?: string[];
    timeout_minutes?: number;
  } = {}
): Promise<HumanRequestInfo> {
  return request("/api/v1/human-requests", {
    method: "POST",
    body: {
      team_id: teamId,
      agent_id: agentId,
      kind,
      question,
      task_id: opts.task_id,
      options: opts.options || [],
      timeout_minutes: opts.timeout_minutes,
    },
  });
}

export async function respondToHumanRequest(
  requestId: number,
  response: string,
  respondedBy?: string
): Promise<HumanRequestInfo> {
  return request(`/api/v1/human-requests/${requestId}/respond`, {
    method: "POST",
    body: { response, responded_by: respondedBy },
  });
}

export async function getHumanRequest(
  requestId: number
): Promise<HumanRequestInfo> {
  return request(`/api/v1/human-requests/${requestId}`);
}

/**
 * Poll for a human request response — blocks until resolved or timed out.
 *
 * Learn: When a coding agent (Claude Code, Codex) calls ask_human(wait=true),
 * the MCP tool needs to block until the human responds. Since we're in an MCP
 * stdio process with no PG LISTEN access, we poll the HTTP API.
 *
 * Default: poll every 5 seconds, timeout after 1 hour.
 */
export async function pollForResponse(
  requestId: number,
  pollIntervalMs: number = 5000,
  timeoutMs: number = 3600000
): Promise<HumanRequestInfo> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const hr = await getHumanRequest(requestId);
    if (hr.status !== "pending") {
      return hr;
    }
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  throw new Error(
    `Timed out waiting for human response to request ${requestId} after ${Math.round(timeoutMs / 1000)}s`
  );
}

export async function listHumanRequests(
  teamId: string,
  opts: { status?: string; agent_id?: string; task_id?: number } = {}
): Promise<HumanRequestInfo[]> {
  const params: Record<string, string> = {};
  if (opts.status) params.status = opts.status;
  if (opts.agent_id) params.agent_id = opts.agent_id;
  if (opts.task_id) params.task_id = String(opts.task_id);
  return request(`/api/v1/teams/${teamId}/human-requests`, { params });
}

// ─── Phase 8: Code Review + Merge ───────────────────────

export interface ReviewComment {
  id: number;
  review_id: number;
  author_id: string;
  author_type: string;
  file_path: string | null;
  line_number: number | null;
  content: string;
  created_at: string;
}

export interface ReviewInfo {
  id: number;
  task_id: number;
  attempt: number;
  reviewer_id: string | null;
  reviewer_type: string;
  verdict: string | null;
  summary: string | null;
  created_at: string;
  resolved_at: string | null;
  comments: ReviewComment[];
}

export interface MergeJobInfo {
  id: number;
  task_id: number;
  repo_id: string;
  status: string;
  strategy: string;
  error: string | null;
  merge_commit: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface MergeStatus {
  task_id: number;
  review_verdict: string | null;
  review_attempt: number;
  merge_jobs: MergeJobInfo[];
  can_merge: boolean;
}

export async function requestReview(
  taskId: number,
  opts: { reviewer_id?: string; reviewer_type?: string } = {}
): Promise<ReviewInfo> {
  return request(`/api/v1/tasks/${taskId}/reviews`, {
    method: "POST",
    body: {
      reviewer_id: opts.reviewer_id,
      reviewer_type: opts.reviewer_type || "user",
    },
  });
}

export async function approveTask(
  taskId: number,
  opts: { summary?: string; reviewer_id?: string } = {}
): Promise<ReviewInfo> {
  return request(`/api/v1/tasks/${taskId}/approve`, {
    method: "POST",
    body: {
      verdict: "approve",
      summary: opts.summary,
      reviewer_id: opts.reviewer_id,
      reviewer_type: "user",
    },
  });
}

export async function rejectTask(
  taskId: number,
  opts: { summary?: string; reviewer_id?: string } = {}
): Promise<ReviewInfo> {
  return request(`/api/v1/tasks/${taskId}/reject`, {
    method: "POST",
    body: {
      verdict: "reject",
      summary: opts.summary,
      reviewer_id: opts.reviewer_id,
      reviewer_type: "user",
    },
  });
}

export async function getMergeStatus(taskId: number): Promise<MergeStatus> {
  return request(`/api/v1/tasks/${taskId}/merge-status`);
}

export async function listReviews(taskId: number): Promise<ReviewInfo[]> {
  return request(`/api/v1/tasks/${taskId}/reviews`);
}

/**
 * Get the latest review feedback for a task — formatted for agent consumption.
 *
 * Learn: Agents call this to read review comments when re-dispatched after
 * a request_changes verdict. Returns the latest review with verdict + comments.
 */
export async function getReviewFeedback(taskId: number): Promise<{
  has_feedback: boolean;
  review: ReviewInfo | null;
  formatted_feedback: string;
}> {
  const reviews = await listReviews(taskId);
  const latestWithChanges = reviews.find(r => r.verdict === "request_changes");

  if (!latestWithChanges) {
    return { has_feedback: false, review: null, formatted_feedback: "No review feedback found." };
  }

  const lines: string[] = [`## Review Feedback (Attempt #${latestWithChanges.attempt})`];
  if (latestWithChanges.summary) {
    lines.push(`\n**Summary:** ${latestWithChanges.summary}\n`);
  }
  if (latestWithChanges.comments.length > 0) {
    lines.push("**Comments to address:**");
    for (const c of latestWithChanges.comments) {
      const loc = c.file_path ? `${c.file_path}:${c.line_number || ""}` : "General";
      lines.push(`- **${loc}**: ${c.content}`);
    }
  }

  return {
    has_feedback: true,
    review: latestWithChanges,
    formatted_feedback: lines.join("\n"),
  };
}

// ─── Phase 9: Auth ──────────────────────────────────────

export interface AuthIdentity {
  type: string; // "user" | "api_key"
  id?: string;
  email?: string;
  name?: string;
  org_id?: string;
  scopes?: string[];
}

export async function authenticate(apiKey: string): Promise<AuthIdentity> {
  const url = new URL("/api/v1/auth/me", API_URL);
  const resp = await fetch(url.toString(), {
    headers: {
      "x-api-key": apiKey,
    },
  });
  if (!resp.ok) {
    throw new Error(`Authentication failed: ${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<AuthIdentity>;
}

// ─── Phase 10: Webhooks + Settings ─────────────────────

export interface WebhookInfo {
  id: string;
  org_id: string;
  team_id: string | null;
  name: string;
  provider: string;
  secret: string;
  events: string[];
  active: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WebhookDeliveryInfo {
  id: number;
  webhook_id: string;
  event_type: string;
  payload: Record<string, unknown> | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface TeamSettingsInfo {
  team_id: string;
  team_name: string;
  settings: Record<string, unknown>;
}

export async function createWebhook(
  orgId: string,
  name: string,
  opts: {
    team_id?: string;
    provider?: string;
    events?: string[];
    config?: Record<string, unknown>;
  } = {}
): Promise<WebhookInfo> {
  return request("/api/v1/webhooks", {
    method: "POST",
    body: {
      org_id: orgId,
      name,
      team_id: opts.team_id,
      provider: opts.provider || "github",
      events: opts.events || ["push", "pull_request"],
      config: opts.config || {},
    },
  });
}

export async function listWebhooks(
  orgId: string,
  opts: { team_id?: string; active_only?: boolean } = {}
): Promise<WebhookInfo[]> {
  const params: Record<string, string> = {};
  if (opts.team_id) params.team_id = opts.team_id;
  if (opts.active_only) params.active_only = "true";
  return request(`/api/v1/webhooks/orgs/${orgId}`, { params });
}

export async function getWebhook(webhookId: string): Promise<WebhookInfo> {
  return request(`/api/v1/webhooks/${webhookId}`);
}

export async function updateWebhook(
  webhookId: string,
  updates: {
    name?: string;
    events?: string[];
    active?: boolean;
    config?: Record<string, unknown>;
  }
): Promise<WebhookInfo> {
  return request(`/api/v1/webhooks/${webhookId}`, {
    method: "PATCH",
    body: updates,
  });
}

export async function deleteWebhook(webhookId: string): Promise<{ deleted: boolean }> {
  return request(`/api/v1/webhooks/${webhookId}`, { method: "DELETE" });
}

export async function listWebhookDeliveries(
  webhookId: string,
  limit: number = 50
): Promise<WebhookDeliveryInfo[]> {
  return request(`/api/v1/webhooks/${webhookId}/deliveries`, {
    params: { limit: String(limit) },
  });
}

export async function getTeamSettings(teamId: string): Promise<TeamSettingsInfo> {
  return request(`/api/v1/settings/teams/${teamId}`);
}

export async function updateTeamSettings(
  teamId: string,
  settings: Record<string, unknown>
): Promise<TeamSettingsInfo> {
  return request(`/api/v1/settings/teams/${teamId}`, {
    method: "PATCH",
    body: settings,
  });
}

// ─── Team Conventions ───────────────────────────────────

export interface Convention {
  key: string;
  content: string;
  active: boolean;
}

export async function getTeamConventions(teamId: string): Promise<Convention[]> {
  return request(`/api/v1/settings/teams/${teamId}/conventions`);
}

export async function addTeamConvention(
  teamId: string,
  key: string,
  content: string,
  active: boolean = true
): Promise<Convention> {
  return request(`/api/v1/settings/teams/${teamId}/conventions`, {
    method: "POST",
    body: { key, content, active },
  });
}

// ─── Phase 16: Multi-Agent Orchestration ─────────────

/**
 * Poll for task completion — blocks until task reaches a terminal status.
 *
 * Learn: Manager agents use this to wait for engineer tasks to finish.
 * Similar to pollForResponse but watches task status instead.
 * Terminal states: done, cancelled, in_review (engineers move to in_review when done).
 */
export async function pollForTaskCompletion(
  taskId: number,
  pollIntervalMs: number = 10000,
  timeoutMs: number = 3600000,
  terminalStatuses: string[] = ["done", "cancelled", "in_review"]
): Promise<Task> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const task = await getTask(taskId);
    if (terminalStatuses.includes(task.status)) {
      return task;
    }
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  throw new Error(
    `Timed out waiting for task ${taskId} to complete after ${Math.round(timeoutMs / 1000)}s`
  );
}

export async function createTasksBatch(
  teamId: string,
  tasks: Array<{
    title: string;
    description?: string;
    priority?: string;
    assignee_id?: string;
    depends_on_indices?: number[];
    tags?: string[];
  }>
): Promise<Task[]> {
  return request(`/api/v1/teams/${teamId}/tasks/batch`, {
    method: "POST",
    body: { tasks },
  });
}

// ─── Tier 1: Git Push + PR ──────────────────────────────

export interface PushResult {
  ok: boolean;
  stdout: string;
  stderr: string;
}

export interface PRInfo {
  pr_url?: string;
  pr_number?: number;
  error?: string;
}

export async function pushBranch(
  taskId: number,
  repoId: string,
  opts: { remote?: string; force?: boolean } = {}
): Promise<PushResult> {
  const params: Record<string, string> = { repo_id: repoId };
  if (opts.remote) params.remote = opts.remote;
  if (opts.force) params.force = "true";
  return request(`/api/v1/tasks/${taskId}/push`, {
    method: "POST",
    params,
  });
}

export async function createPR(
  taskId: number,
  repoId: string,
  opts: {
    title?: string;
    body?: string;
    draft?: boolean;
    base_branch?: string;
  } = {}
): Promise<PRInfo> {
  return request(`/api/v1/tasks/${taskId}/pr`, {
    method: "POST",
    body: {
      repo_id: repoId,
      title: opts.title,
      body: opts.body,
      draft: opts.draft,
      base_branch: opts.base_branch,
    },
  });
}

export async function getPRInfo(taskId: number): Promise<PRInfo> {
  return request(`/api/v1/tasks/${taskId}/pr`);
}

// ─── Tier 1: Review Verdict (agent) ──────────────────────

export async function submitReviewVerdict(
  reviewId: number,
  verdict: string,
  opts: {
    summary?: string;
    reviewer_id?: string;
    reviewer_type?: string;
  } = {}
): Promise<ReviewInfo> {
  return request(`/api/v1/reviews/${reviewId}/verdict`, {
    method: "POST",
    body: {
      verdict,
      summary: opts.summary,
      reviewer_id: opts.reviewer_id,
      reviewer_type: opts.reviewer_type || "agent",
    },
  });
}

export async function addReviewComment(
  reviewId: number,
  opts: {
    author_id: string;
    author_type?: string;
    content: string;
    file_path?: string;
    line_number?: number;
  }
): Promise<ReviewComment> {
  return request(`/api/v1/reviews/${reviewId}/comments`, {
    method: "POST",
    body: {
      author_id: opts.author_id,
      author_type: opts.author_type || "agent",
      content: opts.content,
      file_path: opts.file_path,
      line_number: opts.line_number,
    },
  });
}

// ─── Tier 1: Context Carryover ───────────────────────────

export async function saveContext(
  taskId: number,
  key: string,
  value: string
): Promise<{ key: string; value: string; saved: boolean }> {
  return request(`/api/v1/tasks/${taskId}/context`, {
    method: "POST",
    body: { key, value },
  });
}

export async function getContext(
  taskId: number
): Promise<{ task_id: number; context: Record<string, string> }> {
  return request(`/api/v1/tasks/${taskId}/context`);
}

// ─── Phase 12: Pipelines ─────────────────────────────────

export interface Pipeline {
  id: string;
  org_id: string;
  team_id: string;
  repository_id: string | null;
  created_by: string | null;
  title: string;
  intent: string;
  status: string;
  task_graph: Record<string, unknown> | null;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  budget_limit_usd: number;
  branch_name: string;
  pr_url: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface PipelineTask {
  id: number;
  pipeline_id: string;
  agent_id: string | null;
  title: string;
  description: string;
  complexity: string;
  assigned_role: string;
  status: string;
  dependencies: number[];
  integration_hints: string[];
  estimated_tokens: number;
  branch_name: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface PipelineBudgetLedger {
  id: string;
  pipeline_id: string;
  budget_limit_usd: number;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export async function createPipeline(
  teamId: string,
  title: string,
  intent: string,
  opts: { budget_limit_usd?: number; repository_id?: string } = {}
): Promise<Pipeline> {
  return request(`/api/v1/teams/${teamId}/pipelines`, {
    method: "POST",
    body: { title, intent, ...opts },
  });
}

export async function listPipelines(
  teamId: string,
  opts: { status?: string; limit?: number } = {}
): Promise<Pipeline[]> {
  const params: Record<string, string> = {};
  if (opts.status) params.status = opts.status;
  if (opts.limit) params.limit = String(opts.limit);
  return request(`/api/v1/teams/${teamId}/pipelines`, { params });
}

export async function getPipeline(pipelineId: string): Promise<Pipeline> {
  return request(`/api/v1/pipelines/${pipelineId}`);
}

export async function startPipeline(pipelineId: string): Promise<Pipeline> {
  return request(`/api/v1/pipelines/${pipelineId}/start`, { method: "POST" });
}

export async function getPipelineTasks(pipelineId: string): Promise<PipelineTask[]> {
  return request(`/api/v1/pipelines/${pipelineId}/tasks`);
}

export async function approvePipelinePlan(
  pipelineId: string,
  actorId?: string
): Promise<Pipeline> {
  return request(`/api/v1/pipelines/${pipelineId}/approve-plan`, {
    method: "POST",
    body: { actor_id: actorId },
  });
}

export async function rejectPipelinePlan(
  pipelineId: string,
  opts: { feedback?: string; actor_id?: string } = {}
): Promise<Pipeline> {
  return request(`/api/v1/pipelines/${pipelineId}/reject-plan`, {
    method: "POST",
    body: opts,
  });
}

export async function pausePipeline(pipelineId: string): Promise<Pipeline> {
  return request(`/api/v1/pipelines/${pipelineId}/pause`, { method: "POST" });
}

export async function resumePipeline(pipelineId: string): Promise<Pipeline> {
  return request(`/api/v1/pipelines/${pipelineId}/resume`, { method: "POST" });
}

export async function getPipelineBudget(
  pipelineId: string
): Promise<PipelineBudgetLedger> {
  return request(`/api/v1/pipelines/${pipelineId}/budget`);
}
