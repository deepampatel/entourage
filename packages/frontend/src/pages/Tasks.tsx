/**
 * Tasks page — shows all run tasks across active runs.
 *
 * The team-level Task endpoint is unused by runs (runs create RunTask
 * objects instead). This page fetches all non-draft runs and displays
 * their RunTasks grouped by run, with description and error visibility.
 */

import { useState } from "react";
import { useRuns, useRunTasks } from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";
import { RUN_STATUS_LABELS, type Run, type RunStatus } from "../api/types";

interface TasksProps {
  teamId: string;
}

const TASK_STATUS_LABELS: Record<string, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

function RunTaskGroup({ run }: { run: Run }) {
  const { data: tasks, isLoading } = useRunTasks(run.id);
  const [expandedOutput, setExpandedOutput] = useState<number | null>(null);
  const status = run.status as RunStatus;
  const statusLabel = RUN_STATUS_LABELS[status] || run.status;

  return (
    <div className="task-run-group">
      <div className="task-run-group-header">
        <div className="task-run-group-title">
          <h2>{run.title}</h2>
          <span className={`run-status-badge ${status}`}>
            {statusLabel}
          </span>
        </div>
        {run.pr_url && (
          <a
            href={run.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="run-pr-link"
          >
            Pull Request →
          </a>
        )}
      </div>

      {isLoading && (
        <div className="analytics-loading">Loading tasks...</div>
      )}

      {!isLoading && (!tasks || tasks.length === 0) && (
        <div className="analytics-empty">
          No tasks yet — planning may still be in progress.
        </div>
      )}

      {tasks && tasks.length > 0 && (
        <div className="task-run-list">
          {tasks.map((task, i) => (
            <div
              key={task.id}
              className={`run-task-card${task.error ? " has-error" : ""}`}
            >
              <div className="run-task-card-header">
                <span className="run-task-idx">{i}</span>
                <span
                  className="run-task-complexity"
                  data-complexity={task.complexity}
                >
                  {task.complexity}
                </span>
                <span className="run-task-card-title">{task.title}</span>
                <span
                  className={`task-status task-status-${task.status}`}
                >
                  {TASK_STATUS_LABELS[task.status] || task.status}
                </span>
              </div>
              {task.description && (
                <p className="run-task-description">{task.description}</p>
              )}
              {task.error && (
                <div className="run-task-error">
                  <span className="run-task-error-label">Error:</span>{" "}
                  {task.error}
                </div>
              )}
              {(task.assigned_role || task.dependencies.length > 0) && (
                <div className="run-task-meta">
                  {task.assigned_role && (
                    <span className="run-task-role">{task.assigned_role}</span>
                  )}
                  {task.dependencies.length > 0 && (
                    <span className="run-task-deps">
                      deps: [{task.dependencies.join(", ")}]
                    </span>
                  )}
                </div>
              )}
              {task.result && (
                <div className="agent-output-section">
                  <button
                    className="sandbox-output-toggle"
                    onClick={() =>
                      setExpandedOutput(
                        expandedOutput === task.id ? null : task.id
                      )
                    }
                  >
                    {expandedOutput === task.id ? "Hide Output" : "View Output"}
                  </button>
                  {expandedOutput === task.id && (
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
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Tasks({ teamId }: TasksProps) {
  useTeamSocket(teamId);
  const { data: runs, isLoading } = useRuns(teamId);

  if (isLoading) return <div className="loading">Loading tasks...</div>;

  // Show runs that have or could have tasks (exclude draft and cancelled)
  const activeRuns =
    runs?.filter((r) => !["draft", "cancelled"].includes(r.status)) ?? [];

  return (
    <div className="tasks-page">
      <h1>Tasks</h1>
      {activeRuns.length === 0 && (
        <div className="empty-state">
          <p className="empty-state-title">No tasks yet</p>
          <p className="empty-state-desc">
            Tasks appear here once a run has been planned. Create a run from
            the Runs page to get started.
          </p>
        </div>
      )}
      {activeRuns.map((run) => (
        <RunTaskGroup key={run.id} run={run} />
      ))}
    </div>
  );
}
