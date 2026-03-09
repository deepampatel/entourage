/**
 * Shared API types — mirrors the backend Pydantic schemas.
 */

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

export interface Message {
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

export interface Session {
  id: number;
  agent_id: string;
  task_id: number | null;
  started_at: string;
  ended_at: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  model: string | null;
  error: string | null;
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

export type TaskStatus =
  | "todo"
  | "in_progress"
  | "in_review"
  | "in_approval"
  | "merging"
  | "done"
  | "cancelled";

export type Priority = "low" | "medium" | "high" | "critical";

export const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  in_review: "In Review",
  in_approval: "Approval",
  merging: "Merging",
  done: "Done",
  cancelled: "Cancelled",
};

export const PRIORITY_COLORS: Record<Priority, string> = {
  low: "#6b7280",
  medium: "#3b82f6",
  high: "#f59e0b",
  critical: "#ef4444",
};

// ─── Human Requests ─────────────────────────────────────

export interface HumanRequest {
  id: number;
  team_id: string;
  agent_id: string;
  task_id: number | null;
  kind: string; // "question" | "approval" | "review"
  question: string;
  options: string[];
  status: string; // "pending" | "resolved" | "expired"
  response: string | null;
  responded_by: string | null;
  timeout_at: string | null;
  created_at: string;
  resolved_at: string | null;
}

// ─── Reviews ────────────────────────────────────────────

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

export interface Review {
  id: number;
  task_id: number;
  attempt: number;
  reviewer_id: string | null;
  reviewer_type: string;
  verdict: string | null; // "approve" | "request_changes" | "reject" | null
  summary: string | null;
  created_at: string;
  resolved_at: string | null;
  comments: ReviewComment[];
}

export interface MergeJob {
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
  merge_jobs: MergeJob[];
  can_merge: boolean;
}

// ─── Pipelines ──────────────────────────────────────────

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

export interface Contract {
  id: number;
  pipeline_id: string;
  pipeline_task_id: number | null;
  contract_type: string;
  name: string;
  specification: Record<string, unknown>;
  locked: boolean;
  locked_by: string | null;
  locked_at: string | null;
  created_at: string;
  updated_at: string;
}

export type PipelineStatus =
  | "draft"
  | "planning"
  | "contracting"
  | "awaiting_plan_approval"
  | "executing"
  | "reviewing"
  | "merging"
  | "done"
  | "paused"
  | "failed"
  | "cancelled";

export const PIPELINE_STATUS_LABELS: Record<PipelineStatus, string> = {
  draft: "Draft",
  planning: "Planning",
  contracting: "Generating Contracts",
  awaiting_plan_approval: "Awaiting Approval",
  executing: "Executing",
  reviewing: "Reviewing",
  merging: "Merging",
  done: "Done",
  paused: "Paused",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const PIPELINE_STATUS_COLORS: Record<PipelineStatus, string> = {
  draft: "#6b7280",
  planning: "#8b5cf6",
  contracting: "#a855f7",
  awaiting_plan_approval: "#f59e0b",
  executing: "#3b82f6",
  reviewing: "#06b6d4",
  merging: "#8b5cf6",
  done: "#10b981",
  paused: "#f97316",
  failed: "#ef4444",
  cancelled: "#6b7280",
};
