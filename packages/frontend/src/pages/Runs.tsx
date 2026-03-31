/**
 * Runs page — list, create, and manage run orchestration.
 *
 * Shows run cards with status, cost/budget bar, and task progress.
 * Supports approve/reject for plans and pause/resume for execution.
 */

import { useState } from "react";
import {
  useApprovePlan,
  useCreateRun,
  useGenerateContracts,
  useRepos,
  useRunContracts,
  useRuns,
  useRunTasks,
  useRejectPlan,
  useSandboxRuns,
  useStartRun,
  useTriggerSandboxRun,
} from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";
import { useToast } from "../components/Toast";
import {
  RUN_STATUS_LABELS,
  type Run,
  type RunStatus,
  type RunTask,
  type SandboxRun,
} from "../api/types";

const STATUS_TOOLTIPS: Record<string, string> = {
  draft: "Not started yet",
  planning: "AI is breaking your intent into tasks...",
  contracting: "Generating interface contracts between tasks...",
  awaiting_plan_approval: "Review and approve the plan before execution",
  executing: "Agents are working on tasks",
  reviewing: "Code review in progress",
  merging: "Merging code changes",
  done: "Run complete",
  paused: "Run is paused",
  failed: "One or more tasks failed",
  cancelled: "Run was cancelled",
};

const TEMPLATE_DESCRIPTIONS: Record<string, string> = {
  "": "Full flexibility",
  feature: "Add new functionality",
  bugfix: "Fix a specific issue",
  refactor: "Improve existing code",
  migration: "Upgrade dependencies or infra",
};

interface RunsProps {
  teamId: string;
}

const STATUS_FILTERS: (RunStatus | "all")[] = [
  "all",
  "executing",
  "awaiting_plan_approval",
  "done",
  "failed",
];

function CostBar({ actual, limit }: { actual: number; limit: number }) {
  const pct = limit > 0 ? Math.min((actual / limit) * 100, 100) : 0;
  const color = pct >= 100 ? "var(--semantic-red)" : pct >= 80 ? "var(--semantic-orange)" : "var(--semantic-green)";
  return (
    <div className="cost-bar">
      <div className="cost-bar-fill" style={{ width: `${pct}%`, backgroundColor: color }} />
      <span className="cost-bar-label">
        ${actual.toFixed(2)} / ${limit.toFixed(2)}
      </span>
    </div>
  );
}

function TaskProgress({ tasks }: { tasks: RunTask[] }) {
  if (!tasks.length) return null;
  const done = tasks.filter((t) => t.status === "done").length;
  const failed = tasks.filter((t) => t.status === "failed").length;
  const inProgress = tasks.filter((t) => t.status === "in_progress").length;
  const isParallel = inProgress > 1;
  return (
    <div className="task-progress">
      <span className="task-progress-text">
        {done}/{tasks.length} tasks done
        {inProgress > 0 && (
          <>
            {", "}
            <span className={`running-indicator${isParallel ? " parallel" : ""}`}>
              {inProgress} {isParallel ? "running in parallel" : "running"}
              {isParallel && " ⚡"}
            </span>
          </>
        )}
        {failed > 0 && `, ${failed} failed`}
      </span>
      <div className="task-progress-bar">
        <div
          className="task-progress-fill done"
          style={{ width: `${(done / tasks.length) * 100}%` }}
        />
        <div
          className="task-progress-fill running"
          style={{ width: `${(inProgress / tasks.length) * 100}%` }}
        />
        <div
          className="task-progress-fill failed"
          style={{ width: `${(failed / tasks.length) * 100}%` }}
        />
      </div>
    </div>
  );
}

function SandboxPill({ runs }: { runs: SandboxRun[] | undefined }) {
  if (!runs || runs.length === 0) return <span className="sandbox-pill none">sandbox</span>;
  const latest = runs[0];
  if (latest.exit_code === null) return <span className="sandbox-pill running">running</span>;
  return latest.passed ? (
    <span className="sandbox-pill passed">passed</span>
  ) : (
    <span className="sandbox-pill failed">failed</span>
  );
}

function TaskSandboxDetail({
  runId,
  task,
  teamId,
}: {
  runId: string;
  task: RunTask;
  teamId: string;
}) {
  const [showOutput, setShowOutput] = useState(false);
  const { data: runs } = useSandboxRuns(runId, task.id);
  const triggerRun = useTriggerSandboxRun(teamId);

  const latest = runs?.[0];

  return (
    <div className="sandbox-detail" onClick={(e) => e.stopPropagation()}>
      <div className="sandbox-detail-header">
        <SandboxPill runs={runs} />
        {latest && latest.exit_code !== null && (
          <button
            className="sandbox-output-toggle"
            onClick={() => setShowOutput(!showOutput)}
          >
            {showOutput ? "Hide Output" : "Show Output"}
          </button>
        )}
        <button
          className="run-btn sandbox-trigger-btn"
          onClick={() =>
            triggerRun.mutate({
              runId,
              taskId: task.id,
              testCmd: "pytest tests/",
            })
          }
          disabled={triggerRun.isPending}
        >
          {triggerRun.isPending ? "Running..." : "Run Tests"}
        </button>
      </div>
      {showOutput && latest && (
        <div className="sandbox-output">
          {latest.stdout && (
            <div className="sandbox-output-section">
              <h5>stdout</h5>
              <pre>{latest.stdout}</pre>
            </div>
          )}
          {latest.stderr && (
            <div className="sandbox-output-section">
              <h5>stderr</h5>
              <pre>{latest.stderr}</pre>
            </div>
          )}
          <div className="sandbox-output-meta">
            exit={latest.exit_code} | {latest.duration_seconds.toFixed(1)}s | {latest.image}
          </div>
        </div>
      )}
    </div>
  );
}

function RunCard({
  run,
  teamId,
}: {
  run: Run;
  teamId: string;
}) {
  const shouldAutoExpand = run.status === "awaiting_plan_approval" || run.status === "failed";
  const [expanded, setExpanded] = useState(shouldAutoExpand);
  const [expandedTaskSandbox, setExpandedTaskSandbox] = useState<number | null>(null);
  const [expandedTaskOutput, setExpandedTaskOutput] = useState<number | null>(null);
  const { data: tasks } = useRunTasks(expanded ? run.id : undefined);
  const { data: contracts } = useRunContracts(expanded ? run.id : undefined);
  const approvePlan = useApprovePlan(teamId);
  const rejectPlan = useRejectPlan(teamId);
  const startRun = useStartRun(teamId);
  const generateContracts = useGenerateContracts(teamId);
  const { showToast } = useToast();

  const status = run.status as RunStatus;
  const statusLabel = RUN_STATUS_LABELS[status] || status;

  return (
    <div className="run-card" onClick={() => setExpanded(!expanded)}>
      <div className="run-card-header">
        <div className="run-card-title">
          <h3>{run.title}</h3>
          <span
            className={`run-status-badge ${status}`}
            title={STATUS_TOOLTIPS[status] || ""}
          >
            {statusLabel}
          </span>
        </div>
        <p className="run-intent">{run.intent}</p>
        {run.pr_url && (
          <a
            href={run.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="run-pr-link"
            onClick={(e) => e.stopPropagation()}
          >
            View Pull Request →
          </a>
        )}
      </div>

      <div className="run-card-meta">
        <CostBar actual={run.actual_cost_usd} limit={run.budget_limit_usd} />
        {tasks && <TaskProgress tasks={tasks} />}
      </div>

      {/* Action buttons */}
      <div className="run-actions" onClick={(e) => e.stopPropagation()}>
        {status === "draft" && (
          <button
            className="run-btn run-btn-primary"
            onClick={() => startRun.mutate(run.id)}
            disabled={startRun.isPending}
          >
            Start Planning
          </button>
        )}
        {status === "awaiting_plan_approval" && (
          <>
            <button
              className="run-btn run-btn-success"
              onClick={() => approvePlan.mutate(run.id, {
                onSuccess: () => showToast("Plan approved! Execution starting...", "success"),
              })}
              disabled={approvePlan.isPending}
            >
              Approve Plan
            </button>
            <button
              className="run-btn run-btn-danger"
              onClick={() =>
                rejectPlan.mutate({ runId: run.id })
              }
              disabled={rejectPlan.isPending}
            >
              Reject
            </button>
          </>
        )}
      </div>

      {/* Expanded: show task graph + contracts */}
      {expanded && tasks && (
        <div className="run-tasks-list">
          {(() => {
            const runningTasks = tasks.filter((t) => t.status === "in_progress");
            const isParallel = runningTasks.length > 1;
            return (
              <h4>
                Task Graph ({tasks.length} tasks)
                {isParallel && (
                  <span className="parallel-badge">
                    ⚡ {runningTasks.length} parallel
                  </span>
                )}
              </h4>
            );
          })()}
          {tasks.map((task, i) => {
            const isRunning = task.status === "in_progress";
            const runningTasks = tasks.filter((t) => t.status === "in_progress");
            const isParallel = isRunning && runningTasks.length > 1;
            const sandboxOpen = expandedTaskSandbox === task.id;
            return (
              <div key={task.id} className="run-task-wrapper">
                <div
                  className={`run-task-row${isParallel ? " parallel-running" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpandedTaskSandbox(sandboxOpen ? null : task.id);
                  }}
                >
                  <span className="run-task-idx">{i}</span>
                  <span
                    className="run-task-complexity"
                    data-complexity={task.complexity}
                  >
                    {task.complexity}
                  </span>
                  <span className="run-task-title">{task.title}</span>
                  {isRunning && task.agent_id && (
                    <span className="run-task-agent" title={task.agent_id}>
                      {task.agent_id.slice(0, 8)}
                    </span>
                  )}
                  <span className={`run-task-status run-task-status-${task.status}`}>
                    {task.status}
                    {isParallel && " ⚡"}
                  </span>
                  {task.retry_count > 0 && (
                    <span className="run-task-retry" title={`Retried ${task.retry_count} time(s)`}>
                      {task.retry_count}
                    </span>
                  )}
                  {task.dependencies.length > 0 && (
                    <span className="run-task-deps">
                      deps: [{task.dependencies.join(", ")}]
                    </span>
                  )}
                </div>
                {/* Task description + error details */}
                {(task.description || task.error) && (
                  <div className="run-task-details">
                    {task.description && (
                      <p className="run-task-description">{task.description}</p>
                    )}
                    {task.error && (
                      <div className="run-task-error">
                        <span className="run-task-error-label">Error:</span> {task.error}
                      </div>
                    )}
                  </div>
                )}
                {/* Agent output viewer */}
                {task.result && (
                  <div className="agent-output-section" onClick={(e) => e.stopPropagation()}>
                    <button
                      className="sandbox-output-toggle"
                      onClick={() =>
                        setExpandedTaskOutput(
                          expandedTaskOutput === task.id ? null : task.id
                        )
                      }
                    >
                      {expandedTaskOutput === task.id ? "Hide Output" : "View Output"}
                    </button>
                    {expandedTaskOutput === task.id && (
                      <div className="agent-output">
                        {task.result.stdout && (
                          <div className="sandbox-output-section">
                            <h5>stdout</h5>
                            <pre>{task.result.stdout}</pre>
                          </div>
                        )}
                        {task.result.stderr && (
                          <div className="sandbox-output-section">
                            <h5>stderr</h5>
                            <pre>{task.result.stderr}</pre>
                          </div>
                        )}
                        <div className="sandbox-output-meta">
                          exit={task.result.exit_code ?? "?"} |{" "}
                          {task.result.duration_seconds
                            ? `${task.result.duration_seconds.toFixed(1)}s`
                            : "?"}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {sandboxOpen && (
                  <TaskSandboxDetail
                    runId={run.id}
                    task={task}
                    teamId={teamId}
                  />
                )}
              </div>
            );
          })}

          {/* Contracts section */}
          {contracts && contracts.length > 0 && (
            <div className="run-contracts">
              <h4>Contracts ({contracts.length})</h4>
              {contracts.map((c) => (
                <div key={c.id} className="run-contract-row">
                  <span
                    className="contract-type-badge"
                    data-type={c.contract_type}
                  >
                    {c.contract_type}
                  </span>
                  <span className="contract-name">{c.name}</span>
                  <span
                    className="contract-lock-status"
                    style={{ color: c.locked ? "var(--semantic-green)" : "var(--semantic-orange)" }}
                  >
                    {c.locked ? "locked" : "pending"}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Generate contracts button for eligible runs */}
          {status === "awaiting_plan_approval" &&
            (!contracts || contracts.length === 0) &&
            tasks.length >= 2 && (
              <div
                className="run-actions"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  className="run-btn run-btn-secondary"
                  onClick={() => generateContracts.mutate(run.id)}
                  disabled={generateContracts.isPending}
                >
                  Generate Contracts
                </button>
              </div>
            )}
        </div>
      )}
    </div>
  );
}

// ─── Create Run Form ──────────────────────────────

function CreateRunForm({
  teamId,
  onClose,
}: {
  teamId: string;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [intent, setIntent] = useState("");
  const [budget, setBudget] = useState(10);
  const [template, setTemplate] = useState("");
  const [repositoryId, setRepositoryId] = useState("");
  const createRun = useCreateRun(teamId);
  const { data: repos } = useRepos(teamId);
  const { showToast } = useToast();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createRun.mutate(
      {
        title,
        intent,
        budget_limit_usd: budget,
        ...(template ? { template } : {}),
        ...(repositoryId ? { repository_id: repositoryId } : {}),
      },
      {
        onSuccess: () => {
          showToast("Run created! Planning will start shortly.", "success");
          onClose();
        },
      }
    );
  };

  return (
    <form className="create-run-form" onSubmit={handleSubmit}>
      <h3>New Run</h3>
      <p className="form-help">
        A run takes your description and turns it into working code.
      </p>
      <div className="template-picker">
        {["", "feature", "bugfix", "refactor", "migration"].map((t) => (
          <button
            key={t}
            type="button"
            className={`filter-tab${template === t ? " active" : ""}`}
            onClick={() => setTemplate(t)}
            title={TEMPLATE_DESCRIPTIONS[t]}
          >
            {t || "Custom"}
          </button>
        ))}
      </div>
      <p className="form-help" style={{ marginTop: "-0.25rem" }}>
        {TEMPLATE_DESCRIPTIONS[template]}
      </p>
      <input
        type="text"
        placeholder="Title (e.g. Add OAuth2 login)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />
      <textarea
        placeholder={"Describe what you want built in detail. The AI planner will decompose this into tasks.\n\nExample: Add user authentication with JWT tokens. Create login/register endpoints, password hashing with bcrypt, and protect all API routes with auth middleware."}
        value={intent}
        onChange={(e) => setIntent(e.target.value)}
        rows={5}
        required
      />
      <div>
        <label>
          Budget limit (USD):
          <input
            type="number"
            min={0.01}
            max={1000}
            step={0.01}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
          />
        </label>
        <p className="form-help">
          Max spend on AI API calls. $5-10 for small tasks, $20-50 for features.
        </p>
      </div>
      {repos && repos.length > 0 && (
        <div>
          <label>
            Repository:
            <select
              value={repositoryId}
              onChange={(e) => setRepositoryId(e.target.value)}
              className="create-run-select"
            >
              <option value="">All repositories</option>
              {repos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.local_path})
                </option>
              ))}
            </select>
          </label>
          <p className="form-help">
            Target a specific repo, or leave blank for multi-repo runs.
          </p>
        </div>
      )}
      <div className="form-actions">
        <button type="submit" className="run-btn run-btn-primary" disabled={createRun.isPending}>
          Create
        </button>
        <button type="button" className="run-btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ─── Main Page ─────────────────────────────────────────

export function Runs({ teamId }: RunsProps) {
  useTeamSocket(teamId);

  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [showCreate, setShowCreate] = useState(false);

  const { data: runs, isLoading } = useRuns(
    teamId,
    statusFilter === "all" ? undefined : statusFilter
  );

  if (isLoading) return <div className="loading">Loading runs...</div>;

  return (
    <div className="runs-page">
      <div className="runs-header">
        <h1>Runs</h1>
        <button
          className="run-btn run-btn-primary"
          onClick={() => setShowCreate(true)}
        >
          + New Run
        </button>
      </div>

      {showCreate && (
        <CreateRunForm
          teamId={teamId}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Filter bar */}
      <div className="filter-bar">
        <input
          type="text"
          placeholder="Search runs..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="search-input"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="status-filter-dropdown"
        >
          <option value="all">All Statuses</option>
          <option value="executing">Executing</option>
          <option value="reviewing">Reviewing</option>
          <option value="done">Done</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      {/* Status filters */}
      <div className="run-filters">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            className={`filter-tab ${statusFilter === s ? "active" : ""}`}
            onClick={() => setStatusFilter(s)}
          >
            {s === "all"
              ? "All"
              : RUN_STATUS_LABELS[s as RunStatus] || s}
          </button>
        ))}
      </div>

      {/* Run list */}
      <div className="run-list">
        {runs?.length === 0 && (
          <div className="empty-state">
            <p className="empty-state-title">No runs yet</p>
            <p className="empty-state-desc">
              A run takes your description and turns it into working code.
              Agents plan the work, write code, run tests, and open a PR.
            </p>
            <button
              className="run-btn run-btn-primary empty-state-cta"
              onClick={() => setShowCreate(true)}
            >
              + Create Your First Run
            </button>
          </div>
        )}
        {runs?.map((r) => (
          <RunCard key={r.id} run={r} teamId={teamId} />
        ))}
      </div>
    </div>
  );
}
