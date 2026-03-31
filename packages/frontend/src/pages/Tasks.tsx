/**
 * Tasks page — Kanban board showing all run tasks across active runs.
 *
 * 4 columns: Todo, In Progress, Done, Failed
 * Click a card → sidebar panel slides in with full details.
 */

import { useState, useMemo } from "react";
import { useRuns, useAllRunTasks } from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";
import type { Run, RunTask } from "../api/types";

interface TasksProps {
  teamId: string;
}

const KANBAN_COLUMNS = [
  { status: "todo", label: "To Do", color: "var(--text-muted)" },
  { status: "in_progress", label: "In Progress", color: "var(--semantic-blue)" },
  { status: "done", label: "Done", color: "var(--semantic-green)" },
  { status: "failed", label: "Failed", color: "var(--semantic-red)" },
] as const;

// ─── Kanban Card ──────────────────────────────────────

function KanbanCard({
  task,
  runTitle,
  onClick,
  isSelected,
}: {
  task: RunTask;
  runTitle: string;
  onClick: () => void;
  isSelected: boolean;
}) {
  return (
    <div
      className={`kanban-card${task.error ? " has-error" : ""}${isSelected ? " selected" : ""}`}
      onClick={onClick}
    >
      <div className="kanban-card-title">{task.title}</div>
      <div className="kanban-card-meta">
        <span className="run-task-complexity" data-complexity={task.complexity}>
          {task.complexity}
        </span>
        <span className="kanban-card-role">{task.assigned_role}</span>
        {task.retry_count > 0 && (
          <span className="kanban-card-retry">retry {task.retry_count}</span>
        )}
        {task.result?.duration_seconds && (
          <span className="kanban-card-duration">
            {task.result.duration_seconds.toFixed(0)}s
          </span>
        )}
      </div>
      <div className="kanban-card-run" title={runTitle}>{runTitle}</div>
    </div>
  );
}

// ─── Sidebar Panel ────────────────────────────────────

function TaskSidePanel({
  task,
  runTitle,
  onClose,
}: {
  task: RunTask;
  runTitle: string;
  onClose: () => void;
}) {
  return (
    <>
      <div className="task-sidepanel-backdrop" onClick={onClose} />
      <div className="task-sidepanel">
        <button className="task-sidepanel-close" onClick={onClose}>
          &times;
        </button>

        <h2>{task.title}</h2>

        <div className="task-sidepanel-badges">
          <span className={`task-status task-status-${task.status}`}>
            {task.status.replace("_", " ")}
          </span>
          <span className="run-task-complexity" data-complexity={task.complexity}>
            {task.complexity}
          </span>
          <span className="kanban-card-role">{task.assigned_role}</span>
        </div>

        <div className="task-sidepanel-field">
          <span className="task-sidepanel-label">Run</span>
          <span className="task-sidepanel-value">{runTitle}</span>
        </div>

        {task.agent_id && (
          <div className="task-sidepanel-field">
            <span className="task-sidepanel-label">Agent</span>
            <span className="task-sidepanel-value" title={task.agent_id}>
              {task.agent_id.slice(0, 8)}...
            </span>
          </div>
        )}

        {task.dependencies.length > 0 && (
          <div className="task-sidepanel-field">
            <span className="task-sidepanel-label">Dependencies</span>
            <span className="task-sidepanel-value">
              [{task.dependencies.join(", ")}]
            </span>
          </div>
        )}

        {task.retry_count > 0 && (
          <div className="task-sidepanel-field">
            <span className="task-sidepanel-label">Retries</span>
            <span className="task-sidepanel-value">{task.retry_count}</span>
          </div>
        )}

        <div className="task-sidepanel-divider" />

        {task.description && (
          <div className="task-sidepanel-section">
            <span className="task-sidepanel-label">Description</span>
            <p className="task-sidepanel-description">{task.description}</p>
          </div>
        )}

        {task.error && (
          <div className="task-sidepanel-section">
            <span className="task-sidepanel-label">Error</span>
            <div className="task-sidepanel-error">{task.error}</div>
          </div>
        )}

        {task.result && (
          <>
            <div className="task-sidepanel-divider" />
            <div className="task-sidepanel-section">
              <span className="task-sidepanel-label">Output</span>
              <div className="task-sidepanel-output-meta">
                exit={task.result.exit_code ?? "?"} |{" "}
                {task.result.duration_seconds
                  ? `${task.result.duration_seconds.toFixed(1)}s`
                  : "?"}
              </div>
              {task.result.stdout && (
                <div className="task-sidepanel-output">
                  <h5>stdout</h5>
                  <pre>{task.result.stdout}</pre>
                </div>
              )}
              {task.result.stderr && (
                <div className="task-sidepanel-output">
                  <h5>stderr</h5>
                  <pre>{task.result.stderr}</pre>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ─── Main Page ────────────────────────────────────────

export function Tasks({ teamId }: TasksProps) {
  useTeamSocket(teamId);

  const { data: runs, isLoading: runsLoading } = useRuns(teamId);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);

  // Get all non-draft run IDs
  const activeRuns = useMemo(
    () => runs?.filter((r) => !["draft", "cancelled"].includes(r.status)) ?? [],
    [runs]
  );
  const runIds = useMemo(() => activeRuns.map((r) => r.id), [activeRuns]);
  const runMap = useMemo(() => {
    const m = new Map<string, Run>();
    activeRuns.forEach((r) => m.set(r.id, r));
    return m;
  }, [activeRuns]);

  const { data: allTasks, isLoading: tasksLoading } = useAllRunTasks(runIds);

  const isLoading = runsLoading || tasksLoading;

  // Bucket tasks by status
  const columns = useMemo(() => {
    return KANBAN_COLUMNS.map((col) => ({
      ...col,
      tasks: (allTasks ?? []).filter((t) => t.status === col.status),
    }));
  }, [allTasks]);

  // Selected task (looked up from live data)
  const selectedTask = selectedTaskId
    ? allTasks?.find((t) => t.id === selectedTaskId) ?? null
    : null;

  if (isLoading) return <div className="loading">Loading tasks...</div>;

  const totalTasks = allTasks?.length ?? 0;

  return (
    <div className="tasks-page">
      <div className="tasks-header">
        <h1>Tasks</h1>
        <span className="tasks-count">{totalTasks} tasks across {activeRuns.length} runs</span>
      </div>

      {totalTasks === 0 ? (
        <div className="empty-state">
          <p className="empty-state-title">No tasks yet</p>
          <p className="empty-state-desc">
            Tasks appear here once a run has been planned. Create a run from
            the Runs page to get started.
          </p>
        </div>
      ) : (
        <div className="kanban-board">
          {columns.map((col) => (
            <div key={col.status} className="kanban-column">
              <div className="kanban-header">
                <span className="kanban-title" style={{ color: col.color }}>
                  {col.label}
                </span>
                <span className="kanban-count">{col.tasks.length}</span>
              </div>
              <div className="kanban-cards">
                {col.tasks.map((task) => (
                  <KanbanCard
                    key={task.id}
                    task={task}
                    runTitle={runMap.get(task.run_id)?.title ?? "Unknown run"}
                    onClick={() => setSelectedTaskId(task.id)}
                    isSelected={selectedTaskId === task.id}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedTask && (
        <TaskSidePanel
          task={selectedTask}
          runTitle={runMap.get(selectedTask.run_id)?.title ?? "Unknown run"}
          onClose={() => setSelectedTaskId(null)}
        />
      )}
    </div>
  );
}
