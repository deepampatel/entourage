/**
 * Pipelines page — list, create, and manage pipeline orchestration.
 *
 * Shows pipeline cards with status, cost/budget bar, and task progress.
 * Supports approve/reject for plans and pause/resume for execution.
 */

import { useState } from "react";
import {
  useApprovePlan,
  useCreatePipeline,
  useGenerateContracts,
  usePipelineContracts,
  usePipelines,
  usePipelineTasks,
  useRejectPlan,
  useStartPipeline,
} from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";
import {
  PIPELINE_STATUS_COLORS,
  PIPELINE_STATUS_LABELS,
  type Pipeline,
  type PipelineStatus,
  type PipelineTask,
} from "../api/types";

interface PipelinesProps {
  teamId: string;
}

const STATUS_FILTERS: (PipelineStatus | "all")[] = [
  "all",
  "executing",
  "awaiting_plan_approval",
  "done",
  "failed",
];

function CostBar({ actual, limit }: { actual: number; limit: number }) {
  const pct = limit > 0 ? Math.min((actual / limit) * 100, 100) : 0;
  const color = pct >= 100 ? "#ef4444" : pct >= 80 ? "#f59e0b" : "#10b981";
  return (
    <div className="cost-bar">
      <div className="cost-bar-fill" style={{ width: `${pct}%`, backgroundColor: color }} />
      <span className="cost-bar-label">
        ${actual.toFixed(2)} / ${limit.toFixed(2)}
      </span>
    </div>
  );
}

function TaskProgress({ tasks }: { tasks: PipelineTask[] }) {
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

function PipelineCard({
  pipeline,
  teamId,
}: {
  pipeline: Pipeline;
  teamId: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: tasks } = usePipelineTasks(expanded ? pipeline.id : undefined);
  const { data: contracts } = usePipelineContracts(expanded ? pipeline.id : undefined);
  const approvePlan = useApprovePlan(teamId);
  const rejectPlan = useRejectPlan(teamId);
  const startPipeline = useStartPipeline(teamId);
  const generateContracts = useGenerateContracts(teamId);

  const status = pipeline.status as PipelineStatus;
  const statusColor = PIPELINE_STATUS_COLORS[status] || "#6b7280";
  const statusLabel = PIPELINE_STATUS_LABELS[status] || status;

  return (
    <div className="pipeline-card" onClick={() => setExpanded(!expanded)}>
      <div className="pipeline-card-header">
        <div className="pipeline-card-title">
          <h3>{pipeline.title}</h3>
          <span
            className="pipeline-status-badge"
            style={{ backgroundColor: statusColor }}
          >
            {statusLabel}
          </span>
        </div>
        <p className="pipeline-intent">{pipeline.intent}</p>
      </div>

      <div className="pipeline-card-meta">
        <CostBar actual={pipeline.actual_cost_usd} limit={pipeline.budget_limit_usd} />
        {tasks && <TaskProgress tasks={tasks} />}
      </div>

      {/* Action buttons */}
      <div className="pipeline-actions" onClick={(e) => e.stopPropagation()}>
        {status === "draft" && (
          <button
            className="pipeline-btn pipeline-btn-primary"
            onClick={() => startPipeline.mutate(pipeline.id)}
            disabled={startPipeline.isPending}
          >
            Start Planning
          </button>
        )}
        {status === "awaiting_plan_approval" && (
          <>
            <button
              className="pipeline-btn pipeline-btn-success"
              onClick={() => approvePlan.mutate(pipeline.id)}
              disabled={approvePlan.isPending}
            >
              Approve Plan
            </button>
            <button
              className="pipeline-btn pipeline-btn-danger"
              onClick={() =>
                rejectPlan.mutate({ pipelineId: pipeline.id })
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
        <div className="pipeline-tasks-list">
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
            return (
              <div
                key={task.id}
                className={`pipeline-task-row${isParallel ? " parallel-running" : ""}`}
              >
                <span className="pipeline-task-idx">{i}</span>
                <span
                  className="pipeline-task-complexity"
                  data-complexity={task.complexity}
                >
                  {task.complexity}
                </span>
                <span className="pipeline-task-title">{task.title}</span>
                {isRunning && task.agent_id && (
                  <span className="pipeline-task-agent" title={task.agent_id}>
                    🤖 {task.agent_id.slice(0, 8)}
                  </span>
                )}
                <span
                  className="pipeline-task-status"
                  style={{
                    color:
                      task.status === "done"
                        ? "#10b981"
                        : task.status === "failed"
                          ? "#ef4444"
                          : task.status === "in_progress"
                            ? "#3b82f6"
                            : "#6b7280",
                  }}
                >
                  {task.status}
                  {isParallel && " ⚡"}
                </span>
                {task.retry_count > 0 && (
                  <span className="pipeline-task-retry" title={`Retried ${task.retry_count} time(s)`}>
                    🔄 {task.retry_count}
                  </span>
                )}
                {task.dependencies.length > 0 && (
                  <span className="pipeline-task-deps">
                    deps: [{task.dependencies.join(", ")}]
                  </span>
                )}
              </div>
            );
          })}

          {/* Contracts section */}
          {contracts && contracts.length > 0 && (
            <div className="pipeline-contracts">
              <h4>Contracts ({contracts.length})</h4>
              {contracts.map((c) => (
                <div key={c.id} className="pipeline-contract-row">
                  <span
                    className="contract-type-badge"
                    data-type={c.contract_type}
                  >
                    {c.contract_type}
                  </span>
                  <span className="contract-name">{c.name}</span>
                  <span
                    className="contract-lock-status"
                    style={{ color: c.locked ? "#10b981" : "#f59e0b" }}
                  >
                    {c.locked ? "locked" : "pending"}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Generate contracts button for eligible pipelines */}
          {status === "awaiting_plan_approval" &&
            (!contracts || contracts.length === 0) &&
            tasks.length >= 2 && (
              <div
                className="pipeline-actions"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  className="pipeline-btn pipeline-btn-secondary"
                  onClick={() => generateContracts.mutate(pipeline.id)}
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

// ─── Create Pipeline Form ──────────────────────────────

function CreatePipelineForm({
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
  const createPipeline = useCreatePipeline(teamId);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createPipeline.mutate(
      {
        title,
        intent,
        budget_limit_usd: budget,
        ...(template ? { template } : {}),
      },
      { onSuccess: onClose }
    );
  };

  return (
    <form className="create-pipeline-form" onSubmit={handleSubmit}>
      <h3>New Pipeline</h3>
      <div className="template-picker">
        {["", "feature", "bugfix", "refactor", "migration"].map((t) => (
          <button
            key={t}
            type="button"
            className={`filter-tab${template === t ? " active" : ""}`}
            onClick={() => setTemplate(t)}
          >
            {t || "Custom"}
          </button>
        ))}
      </div>
      <input
        type="text"
        placeholder="Title (e.g. Add OAuth2 login)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />
      <textarea
        placeholder="Intent — describe what you want built in detail..."
        value={intent}
        onChange={(e) => setIntent(e.target.value)}
        rows={4}
        required
      />
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
      <div className="form-actions">
        <button type="submit" className="pipeline-btn pipeline-btn-primary" disabled={createPipeline.isPending}>
          Create
        </button>
        <button type="button" className="pipeline-btn" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ─── Main Page ─────────────────────────────────────────

export function Pipelines({ teamId }: PipelinesProps) {
  useTeamSocket(teamId);

  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [showCreate, setShowCreate] = useState(false);

  const { data: pipelines, isLoading } = usePipelines(
    teamId,
    statusFilter === "all" ? undefined : statusFilter
  );

  if (isLoading) return <div className="loading">Loading pipelines...</div>;

  return (
    <div className="pipelines-page">
      <div className="pipelines-header">
        <h1>Pipelines</h1>
        <button
          className="pipeline-btn pipeline-btn-primary"
          onClick={() => setShowCreate(true)}
        >
          + New Pipeline
        </button>
      </div>

      {showCreate && (
        <CreatePipelineForm
          teamId={teamId}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Status filters */}
      <div className="pipeline-filters">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            className={`filter-tab ${statusFilter === s ? "active" : ""}`}
            onClick={() => setStatusFilter(s)}
          >
            {s === "all"
              ? "All"
              : PIPELINE_STATUS_LABELS[s as PipelineStatus] || s}
          </button>
        ))}
      </div>

      {/* Pipeline list */}
      <div className="pipeline-list">
        {pipelines?.length === 0 && (
          <div className="empty-state">
            No pipelines yet. Create one to get started.
          </div>
        )}
        {pipelines?.map((p) => (
          <PipelineCard key={p.id} pipeline={p} teamId={teamId} />
        ))}
      </div>
    </div>
  );
}
