/**
 * Runs page — Vercel-style cards with live status.
 *
 * Each run is a self-contained card showing everything:
 * tasks, status, diff summary, and actions. No expanding needed.
 */

import { useMemo, useState } from "react";
import {
  useApprovePlan,
  useChangeRunStatus,
  useCreateRun,
  useMergeRun,
  useRepos,
  useRunDiff,
  useRuns,
  useRunTasks,
  useRejectPlan,
  useStartRun,
} from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";
import { useToast } from "../components/Toast";
import type { Run, RunStatus, RunTask } from "../api/types";
import { RUN_STATUS_LABELS } from "../api/types";

// ─── Status colors ───────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  draft: "var(--text-faint)",
  planning: "var(--semantic-blue)",
  awaiting_plan_approval: "var(--semantic-orange)",
  executing: "var(--semantic-blue)",
  reviewing: "var(--semantic-purple)",
  merging: "var(--semantic-blue)",
  done: "var(--semantic-green)",
  paused: "var(--semantic-orange)",
  failed: "var(--semantic-red)",
  cancelled: "var(--text-faint)",
};

const FILTERS: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "executing", label: "Running" },
  { value: "reviewing", label: "Review" },
  { value: "awaiting_plan_approval", label: "Needs Approval" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
];

interface RunsProps {
  teamId: string;
}

// ─── Task Pill ───────────────────────────────────────

function TaskPill({ task }: { task: RunTask }) {
  const colors: Record<string, string> = {
    todo: "var(--text-faint)",
    in_progress: "var(--semantic-blue)",
    done: "var(--semantic-green)",
    failed: "var(--semantic-red)",
  };
  const bg: Record<string, string> = {
    todo: "var(--bg-active)",
    in_progress: "var(--semantic-blue-muted)",
    done: "var(--semantic-green-muted)",
    failed: "var(--semantic-red-muted)",
  };

  return (
    <div
      className="task-pill"
      style={{
        background: bg[task.status] || "var(--bg-active)",
        color: colors[task.status] || "var(--text-muted)",
      }}
      title={`${task.title} — ${task.status}`}
    >
      {task.status === "done" && "✓"}
      {task.status === "failed" && "✕"}
      {task.status === "in_progress" && (
        <span className="task-pill-spinner" />
      )}
      <span className="task-pill-label">{task.title.slice(0, 25)}</span>
    </div>
  );
}

// ─── Diff Summary (inline on card) ───────────────────

function DiffSummary({ runId }: { runId: string }) {
  const { data: diffData } = useRunDiff(runId);

  if (!diffData || !diffData.files.length) return null;

  const totalAdd = diffData.files.reduce((s, f) => s + f.additions, 0);
  const totalDel = diffData.files.reduce((s, f) => s + f.deletions, 0);

  return (
    <div className="run-diff-summary">
      <span className="diff-summary-count">
        {diffData.files.length} file{diffData.files.length !== 1 ? "s" : ""}
      </span>
      <span className="diff-summary-add">+{totalAdd}</span>
      <span className="diff-summary-del">-{totalDel}</span>
      <span className="diff-summary-files">
        {diffData.files.slice(0, 3).map((f) => f.path.split("/").pop()).join(", ")}
        {diffData.files.length > 3 && ` +${diffData.files.length - 3} more`}
      </span>
    </div>
  );
}

// ─── Diff Viewer (expandable per-file) ───────────────

function DiffViewer({ runId }: { runId: string }) {
  const { data: diffData } = useRunDiff(runId);
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set());

  if (!diffData?.diff) return null;

  const fileSections = diffData.diff.split(/^diff --git /m).filter(Boolean);

  const toggleFile = (path: string) => {
    const next = new Set(expandedFiles);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setExpandedFiles(next);
  };

  return (
    <div className="diff-reviewer">
      {fileSections.map((section, i) => {
        const lines = section.split("\n");
        const headerMatch = lines[0]?.match(/a\/(.+?) b\/(.+)/);
        const path = headerMatch ? headerMatch[2] : `file-${i}`;
        const isNew = lines.some((l) => l.startsWith("new file"));
        const isExpanded = expandedFiles.has(path);

        const contentLines = lines.filter(
          (l) => l.startsWith("+") || l.startsWith("-") || l.startsWith("@@") || l.startsWith(" ")
        );

        return (
          <div key={path} className="diff-file-section">
            <div
              className={`diff-file-header ${isExpanded ? "expanded" : ""}`}
              onClick={() => toggleFile(path)}
            >
              <span className="diff-file-chevron">{isExpanded ? "▾" : "▸"}</span>
              <span className={`diff-file-badge diff-file-badge-${isNew ? "A" : "M"}`}>
                {isNew ? "New" : "Mod"}
              </span>
              <span className="diff-file-name">
                {path.split("/").slice(0, -1).join("/") + "/"}
                <strong>{path.split("/").pop()}</strong>
              </span>
            </div>
            {isExpanded && (
              <pre className="diff-hunk-block">
                {contentLines.map((line, li) => {
                  let cls = "diff-code-line";
                  if (line.startsWith("+") && !line.startsWith("+++")) cls += " diff-add";
                  else if (line.startsWith("-") && !line.startsWith("---")) cls += " diff-del";
                  else if (line.startsWith("@@")) cls += " diff-hunk-header";
                  return (
                    <div key={li} className={cls}>
                      <span className="diff-line-prefix">
                        {line.startsWith("+") && !line.startsWith("+++") ? "+" :
                         line.startsWith("-") && !line.startsWith("---") ? "-" : " "}
                      </span>
                      <span className="diff-line-content">
                        {line.startsWith("+") || line.startsWith("-") ? line.slice(1) : line}
                      </span>
                    </div>
                  );
                })}
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Run Card ────────────────────────────────────────

function RunCard({ run, teamId }: { run: Run; teamId: string }) {
  const autoExpand = ["awaiting_plan_approval", "failed"].includes(run.status);
  const [expanded, setExpanded] = useState(autoExpand);
  const { data: tasks } = useRunTasks(run.id);
  const approvePlan = useApprovePlan(teamId);
  const rejectPlan = useRejectPlan(teamId);
  const startRun = useStartRun(teamId);
  const changeStatus = useChangeRunStatus(teamId);
  const mergeRun = useMergeRun(teamId);
  const { showToast } = useToast();
  const [showDiff, setShowDiff] = useState(false);
  const [expandedTaskId, setExpandedTaskId] = useState<number | null>(null);

  const status = run.status as RunStatus;
  const dotColor = STATUS_DOT[status] || "var(--text-faint)";
  const label = RUN_STATUS_LABELS[status] || status;

  const doneTasks = tasks?.filter((t) => t.status === "done").length ?? 0;
  const totalTasks = tasks?.length ?? 0;
  const totalDuration = tasks?.reduce((s, t) => s + (t.result?.duration_seconds ?? 0), 0) ?? 0;

  const isActive = ["planning", "executing"].includes(status);
  const needsAction = ["draft", "awaiting_plan_approval", "reviewing"].includes(status);

  return (
    <div className={`run-card-v2 ${isActive ? "active" : ""} ${needsAction ? "needs-action" : ""}`}>
      {/* Header row — click to expand */}
      <div className="run-card-top" onClick={() => setExpanded(!expanded)} style={{ cursor: "pointer" }}>
        <div className="run-card-title-row">
          <h3 className="run-card-title">{run.title}</h3>
          <div className="run-card-status" style={{ color: dotColor }}>
            <span
              className={`status-dot ${isActive ? "pulsing" : ""}`}
              style={{ background: dotColor }}
            />
            {label}
          </div>
        </div>
        {run.branch_name && (
          <span className="run-card-branch">{run.branch_name}</span>
        )}
      </div>

      {/* Task pills */}
      {tasks && tasks.length > 0 && (
        <div className="run-card-tasks">
          <div className="task-pills">
            {tasks.map((t) => (
              <TaskPill key={t.id} task={t} />
            ))}
          </div>
          <span className="run-card-task-meta">
            {doneTasks}/{totalTasks} tasks
            {totalDuration > 0 && ` · ${Math.round(totalDuration)}s`}
            {run.actual_cost_usd > 0 && ` · $${run.actual_cost_usd.toFixed(2)}`}
          </span>
        </div>
      )}

      {/* Diff summary (only when reviewing and has repo) */}
      {status === "reviewing" && run.repository_id && (
        <DiffSummary runId={run.id} />
      )}

      {/* Actions — always visible, contextual */}
      <div className="run-card-actions">
        {status === "draft" && (
          <button
            className="run-action-btn primary"
            onClick={() => startRun.mutate(run.id)}
            disabled={startRun.isPending}
          >
            Start Planning
          </button>
        )}

        {status === "awaiting_plan_approval" && (
          <>
            <button
              className="run-action-btn primary"
              onClick={() => approvePlan.mutate(run.id, {
                onSuccess: () => showToast("Approved — agents are working", "success"),
              })}
              disabled={approvePlan.isPending}
            >
              Approve & Execute
            </button>
            <button
              className="run-action-btn ghost"
              onClick={() => rejectPlan.mutate({ runId: run.id })}
            >
              Reject
            </button>
          </>
        )}

        {status === "reviewing" && (
          <>
            {run.repository_id && (
              <button
                className="run-action-btn ghost"
                onClick={() => setShowDiff(!showDiff)}
              >
                {showDiff ? "Hide Diff" : "Review Diff"}
              </button>
            )}
            {run.repository_id ? (
              <>
                <button
                  className="run-action-btn primary"
                  onClick={() => mergeRun.mutate(
                    { runId: run.id },
                    { onSuccess: () => showToast("Merged to main", "success") }
                  )}
                  disabled={mergeRun.isPending}
                >
                  Approve & Merge
                </button>
                <button
                  className="run-action-btn ghost"
                  onClick={() => mergeRun.mutate(
                    { runId: run.id, create_pr: true },
                    { onSuccess: () => showToast("PR created", "success") }
                  )}
                >
                  Create PR
                </button>
              </>
            ) : (
              <button
                className="run-action-btn primary"
                onClick={() => changeStatus.mutate(
                  { runId: run.id, status: "done" },
                  { onSuccess: () => showToast("Done", "success") }
                )}
              >
                Mark Done
              </button>
            )}
          </>
        )}

        {status === "failed" && (
          <button
            className="run-action-btn ghost"
            onClick={() => changeStatus.mutate(
              { runId: run.id, status: "draft" },
            )}
          >
            Retry
          </button>
        )}

        {["executing", "reviewing", "failed"].includes(status) && (
          <button
            className="run-action-btn danger"
            onClick={() => changeStatus.mutate(
              { runId: run.id, status: "cancelled" },
            )}
          >
            Cancel
          </button>
        )}
      </div>

      {/* Expanded: full task details */}
      {expanded && tasks && tasks.length > 0 && (
        <div className="run-expanded" onClick={(e) => e.stopPropagation()}>
          <div className="run-expanded-header">
            <span className="run-expanded-label">
              Task Graph ({tasks.length} tasks)
            </span>
            {run.intent && (
              <p className="run-intent-text">{run.intent}</p>
            )}
          </div>
          <div className="run-task-list">
            {tasks.map((task, i) => (
              <div
                key={task.id}
                className={`run-task-row ${task.status === "failed" ? "failed" : ""} ${expandedTaskId === task.id ? "selected" : ""}`}
                onClick={() => setExpandedTaskId(expandedTaskId === task.id ? null : task.id)}
              >
                <div className="run-task-summary">
                  <span className="run-task-index">{i}</span>
                  <span className={`run-task-complexity complexity-${task.complexity}`}>
                    {task.complexity}
                  </span>
                  <span className="run-task-title">{task.title}</span>
                  <span className={`run-task-status status-${task.status}`}>
                    {task.status.replace("_", " ")}
                  </span>
                  {task.result?.duration_seconds && (
                    <span className="run-task-duration">
                      {Math.round(task.result.duration_seconds)}s
                    </span>
                  )}
                  {task.dependencies.length > 0 && (
                    <span className="run-task-deps">
                      → [{task.dependencies.join(", ")}]
                    </span>
                  )}
                </div>
                {expandedTaskId === task.id && (
                  <div className="run-task-detail">
                    {task.description && (
                      <div className="run-task-description">{task.description}</div>
                    )}
                    {task.error && (
                      <div className="run-task-error">{task.error}</div>
                    )}
                    {task.agent_id && (
                      <div className="run-task-meta-line">
                        Agent: <code>{task.agent_id.slice(0, 12)}</code>
                        {task.retry_count > 0 && ` · ${task.retry_count} retries`}
                      </div>
                    )}
                    {task.result?.stdout && (
                      <details className="run-task-output">
                        <summary>Output ({task.result.stdout.length} chars)</summary>
                        <pre>{task.result.stdout}</pre>
                      </details>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Diff viewer */}
      {showDiff && status === "reviewing" && run.repository_id && (
        <DiffViewer runId={run.id} />
      )}
    </div>
  );
}

// ─── Create Run (inline command bar) ─────────────────

function CreateBar({
  teamId,
  onCreated,
}: {
  teamId: string;
  onCreated: () => void;
}) {
  const [intent, setIntent] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [budget, setBudget] = useState(10);
  const [repositoryId, setRepositoryId] = useState("");
  const createRun = useCreateRun(teamId);
  const { data: repos } = useRepos(teamId);
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!intent.trim()) return;

    createRun.mutate(
      {
        title: intent.trim().slice(0, 200),
        intent: intent.trim(),
        budget_limit_usd: budget,
        ...(repositoryId ? { repository_id: repositoryId } : {}),
      },
      {
        onSuccess: () => {
          setIntent("");
          setExpanded(false);
          showToast("Run created — planning will start", "success");
          onCreated();
        },
      }
    );
  };

  return (
    <form className="create-bar" onSubmit={handleSubmit}>
      <div className="create-bar-main">
        <input
          type="text"
          className="create-bar-input"
          placeholder="What do you want built?"
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          onFocus={() => setExpanded(true)}
        />
        <button
          type="submit"
          className="create-bar-submit"
          disabled={createRun.isPending || !intent.trim()}
        >
          {createRun.isPending ? "Creating..." : "Create Run"}
        </button>
      </div>
      {expanded && intent.trim() && (
        <div className="create-bar-options">
          <label>
            Budget: ${budget}
            <input
              type="range"
              min={1}
              max={50}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="create-bar-slider"
            />
          </label>
          {repos && repos.length > 0 && (
            <label>
              Repo:
              <select
                value={repositoryId}
                onChange={(e) => setRepositoryId(e.target.value)}
                className="create-bar-select"
              >
                <option value="">Auto-detect</option>
                {repos.map((r) => (
                  <option key={r.id} value={r.id}>{r.name}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
    </form>
  );
}

// ─── Main Page ───────────────────────────────────────

export function Runs({ teamId }: RunsProps) {
  useTeamSocket(teamId);

  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const { data: runs, isLoading } = useRuns(
    teamId,
    filter === "all" ? undefined : filter
  );

  const filtered = useMemo(() => {
    if (!runs) return [];
    if (!search) return runs;
    const q = search.toLowerCase();
    return runs.filter((r) => r.title.toLowerCase().includes(q));
  }, [runs, search]);

  if (isLoading) return <div className="loading">Loading...</div>;

  return (
    <div className="runs-page-v2">
      {/* Command bar */}
      <CreateBar teamId={teamId} onCreated={() => {}} />

      {/* Filters */}
      <div className="runs-toolbar">
        <div className="runs-filters">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              className={`runs-filter ${filter === f.value ? "active" : ""}`}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          className="runs-search"
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Run list */}
      <div className="runs-list-v2">
        {filtered.length === 0 ? (
          <div className="runs-empty">
            <p>{runs?.length ? "No matching runs." : "No runs yet."}</p>
            {!runs?.length && (
              <p className="runs-empty-hint">
                Type what you want built above. Agents will plan, code, test, and open a PR.
              </p>
            )}
          </div>
        ) : (
          filtered.map((r) => <RunCard key={r.id} run={r} teamId={teamId} />)
        )}
      </div>
    </div>
  );
}
