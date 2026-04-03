/**
 * Tasks page — Kanban board showing all run tasks across active runs.
 *
 * 4 columns: Todo, In Progress, Done, Failed
 * Click a card → sidebar panel slides in with full details.
 */

import { useState, useMemo, useCallback } from "react";
import { useRuns, useAllRunTasks } from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";
import { useEscapeKey } from "../hooks/useKeyboard";
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

// ─── Diff Line Parser ─────────────────────────────────

function parseDiffLines(stdout: string): { file: string; additions: number; deletions: number }[] {
  // Parse agent output for file change mentions
  const files: { file: string; additions: number; deletions: number }[] = [];
  const seen = new Set<string>();

  // Match patterns like "Created src/utils/foo.py", "Modified packages/...", etc.
  const patterns = [
    /(?:creat|writ|add|modif|updat|edit)\w*\s+[`"']?([a-zA-Z0-9_./-]+\.\w{1,5})[`"']?/gi,
    /(?:file|path):\s*[`"']?([a-zA-Z0-9_./-]+\.\w{1,5})[`"']?/gi,
  ];

  for (const pat of patterns) {
    for (const match of stdout.matchAll(pat)) {
      const file = match[1];
      if (!seen.has(file) && file.includes("/") && !file.startsWith("http")) {
        seen.add(file);
        files.push({ file, additions: 0, deletions: 0 });
      }
    }
  }
  return files;
}

function DiffBlock({ content }: { content: string }) {
  // Render a unified diff with syntax coloring
  const lines = content.split("\n");
  return (
    <pre className="diff-viewer">
      {lines.map((line, i) => {
        let cls = "diff-line";
        if (line.startsWith("+") && !line.startsWith("+++")) cls += " diff-add";
        else if (line.startsWith("-") && !line.startsWith("---")) cls += " diff-del";
        else if (line.startsWith("@@")) cls += " diff-hunk";
        else if (line.startsWith("diff ") || line.startsWith("index ")) cls += " diff-meta";
        return (
          <div key={i} className={cls}>
            {line}
          </div>
        );
      })}
    </pre>
  );
}

// ─── Sidebar Panel ────────────────────────────────────

type SidePanelTab = "details" | "output" | "changes";

function TaskSidePanel({
  task,
  runTitle,
  onClose,
}: {
  task: RunTask;
  runTitle: string;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<SidePanelTab>("details");

  const changedFiles = useMemo(() => {
    if (!task.result?.stdout) return [];
    return parseDiffLines(task.result.stdout);
  }, [task.result?.stdout]);

  const hasDiff = task.result?.diff;
  const hasOutput = task.result?.stdout || task.result?.stderr;
  const hasChanges = changedFiles.length > 0 || hasDiff;

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
          {task.result?.duration_seconds && (
            <span className="task-duration-badge">
              {task.result.duration_seconds.toFixed(0)}s
            </span>
          )}
        </div>

        {/* Tab bar */}
        <div className="sidepanel-tabs">
          <button
            className={`sidepanel-tab ${activeTab === "details" ? "active" : ""}`}
            onClick={() => setActiveTab("details")}
          >
            Details
          </button>
          <button
            className={`sidepanel-tab ${activeTab === "output" ? "active" : ""}`}
            onClick={() => setActiveTab("output")}
            disabled={!hasOutput}
          >
            Output
          </button>
          <button
            className={`sidepanel-tab ${activeTab === "changes" ? "active" : ""}`}
            onClick={() => setActiveTab("changes")}
            disabled={!hasChanges}
          >
            Changes {hasChanges && `(${changedFiles.length})`}
          </button>
        </div>

        {/* Details tab */}
        {activeTab === "details" && (
          <div className="sidepanel-tab-content">
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

            {task.description && (
              <>
                <div className="task-sidepanel-divider" />
                <div className="task-sidepanel-section">
                  <span className="task-sidepanel-label">Description</span>
                  <p className="task-sidepanel-description">{task.description}</p>
                </div>
              </>
            )}

            {task.error && (
              <div className="task-sidepanel-section">
                <span className="task-sidepanel-label">Error</span>
                <div className="task-sidepanel-error">{task.error}</div>
              </div>
            )}
          </div>
        )}

        {/* Output tab */}
        {activeTab === "output" && task.result && (
          <div className="sidepanel-tab-content">
            <div className="task-sidepanel-output-meta">
              exit={task.result.exit_code ?? "?"} |{" "}
              {task.result.duration_seconds
                ? `${task.result.duration_seconds.toFixed(1)}s`
                : "?"}
            </div>
            {task.result.stdout && (
              <div className="task-sidepanel-output">
                <pre>{task.result.stdout}</pre>
              </div>
            )}
            {task.result.stderr && (
              <div className="task-sidepanel-output stderr">
                <h5>stderr</h5>
                <pre>{task.result.stderr}</pre>
              </div>
            )}
          </div>
        )}

        {/* Changes tab */}
        {activeTab === "changes" && (
          <div className="sidepanel-tab-content">
            {/* File list with diff stat */}
            {changedFiles.length > 0 && (
              <div className="diff-file-list">
                <span className="task-sidepanel-label">
                  Changed Files ({changedFiles.length})
                </span>
                {changedFiles.map((f) => (
                  <div key={f.file} className="diff-file-row">
                    <span className="diff-file-icon">M</span>
                    <span className="diff-file-path">{f.file}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Unified diff if available */}
            {hasDiff ? (
              <div className="diff-section">
                <span className="task-sidepanel-label">Diff</span>
                <DiffBlock content={task.result!.diff as string} />
              </div>
            ) : changedFiles.length > 0 ? (
              <div className="diff-placeholder">
                <p>Full diff available after commit.</p>
                <p className="form-help">
                  Register a repo in Manage → agents will create branches →
                  full git diff shown here.
                </p>
              </div>
            ) : (
              <div className="diff-placeholder">
                <p>No file changes detected.</p>
              </div>
            )}
          </div>
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

  // Escape closes sidebar
  useEscapeKey(useCallback(() => setSelectedTaskId(null), []));

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
