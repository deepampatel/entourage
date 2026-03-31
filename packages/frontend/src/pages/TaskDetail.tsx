/**
 * Task Detail page — full task info with events timeline and review panel.
 *
 * Learn: Shows task metadata, description, events timeline, and reviews.
 * Accessible via /tasks/:taskId route. Uses the existing ReviewPanel
 * component for review display and actions.
 */

import { useParams, Link } from "react-router-dom";
import {
  useTask,
  useTaskEvents,
  useTaskReviews,
  useAgents,
  useApproveTask,
  useRejectTask,
  useArchiveTask,
} from "../hooks/useApi";
import { ReviewPanel } from "../components/ReviewPanel";
import { useToast } from "../components/Toast";
import {
  STATUS_LABELS,
  PRIORITY_COLORS,
  type TaskStatus,
  type Priority,
} from "../api/types";

interface TaskDetailProps {
  teamId: string;
}

export function TaskDetail({ teamId }: TaskDetailProps) {
  const { taskId: taskIdStr } = useParams();
  const taskId = taskIdStr ? Number(taskIdStr) : undefined;

  const { data: task, isLoading: taskLoading } = useTask(taskId);
  const { data: events } = useTaskEvents(taskId);
  const { data: reviews } = useTaskReviews(taskId);
  const { data: agents } = useAgents(teamId);
  const approveMut = useApproveTask(teamId);
  const rejectMut = useRejectTask(teamId);
  const archiveMut = useArchiveTask(teamId);
  const { showToast } = useToast();

  if (taskLoading) {
    return <div className="loading">Loading task...</div>;
  }

  if (!task) {
    return (
      <div className="empty-state-page">
        <h2>Task not found</h2>
        <Link to="/tasks" className="nav-link">
          Back to Tasks
        </Link>
      </div>
    );
  }

  const statusLabel =
    STATUS_LABELS[task.status as TaskStatus] || task.status;
  const priorityColor =
    PRIORITY_COLORS[task.priority as Priority] || "var(--semantic-gray)";
  const assignee = agents?.find((a) => a.id === task.assignee_id);
  const latestReview = reviews?.length ? reviews[reviews.length - 1] : null;

  const showApproveReject =
    task.status === "in_review" || task.status === "in_approval";
  const showArchive = task.status === "done" || task.status === "cancelled";

  return (
    <div className="task-detail">
      {/* Breadcrumb */}
      <div className="task-detail-breadcrumb">
        <Link to="/tasks">Tasks</Link>
        <span> / </span>
        <span>#{task.id}</span>
      </div>

      {/* Header */}
      <div className="task-detail-header">
        <h1>{task.title}</h1>
        <div className="task-detail-meta">
          <span className={`task-status task-status-${task.status}`}>
            {statusLabel}
          </span>
          <span
            className="task-priority"
            style={{ color: priorityColor }}
          >
            {task.priority}
          </span>
          {assignee && (
            <span className="task-assignee">
              Assigned to {assignee.name}
            </span>
          )}
          {task.branch && (
            <span className="task-detail-branch">{task.branch}</span>
          )}
        </div>
      </div>

      {/* Description */}
      {task.description && (
        <div className="task-detail-section">
          <h2>Description</h2>
          <p className="task-detail-description">{task.description}</p>
        </div>
      )}

      {/* Dependent Tasks */}
      {task.dependent_tasks && task.dependent_tasks.length > 0 && (
        <div className="task-detail-section">
          <h2>Depends On</h2>
          <div className="dependent-tasks-grid">
            {task.dependent_tasks.map((dep) => {
              const depStatusLabel =
                STATUS_LABELS[dep.status as TaskStatus] || dep.status;
              const depPriorityColor =
                PRIORITY_COLORS[dep.priority as Priority] ||
                "var(--semantic-gray)";
              const isBlocked = dep.status !== "done";

              return (
                <Link
                  key={dep.id}
                  to={`/tasks/${dep.id}`}
                  className={`dependent-task-card ${
                    isBlocked ? "blocked" : "ready"
                  }`}
                >
                  <div className="dependent-task-header">
                    <span className="dependent-task-id">#{dep.id}</span>
                    {isBlocked && (
                      <span className="dependent-task-blocked-badge">
                        Blocking
                      </span>
                    )}
                  </div>
                  <div className="dependent-task-title">{dep.title}</div>
                  <div className="dependent-task-meta">
                    <span
                      className={`task-status task-status-${dep.status}`}
                    >
                      {depStatusLabel}
                    </span>
                    <span
                      className="dependent-task-priority"
                      style={{ color: depPriorityColor }}
                    >
                      {dep.priority}
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* Metadata */}
      <div className="task-detail-section">
        <h2>Details</h2>
        <div className="task-detail-grid">
          <div className="task-detail-field">
            <span className="task-detail-label">Created</span>
            <span>{new Date(task.created_at).toLocaleString()}</span>
          </div>
          {task.completed_at && (
            <div className="task-detail-field">
              <span className="task-detail-label">Completed</span>
              <span>
                {new Date(task.completed_at).toLocaleString()}
              </span>
            </div>
          )}
          {task.depends_on.length > 0 && (
            <div className="task-detail-field">
              <span className="task-detail-label">Depends on</span>
              <span>
                {task.depends_on.map((id) => (
                  <Link key={id} to={`/tasks/${id}`} className="task-dep-link">
                    #{id}
                  </Link>
                ))}
              </span>
            </div>
          )}
          {task.tags.length > 0 && (
            <div className="task-detail-field">
              <span className="task-detail-label">Tags</span>
              <div className="task-tags">
                {task.tags.map((tag) => (
                  <span key={tag} className="task-tag">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Approve / Reject actions */}
      {(showApproveReject || showArchive) && (
        <div className="task-detail-section">
          <h2>Actions</h2>
          <div className="review-actions">
            {showApproveReject && (
              <>
                <button
                  className="review-btn review-btn-approve"
                  onClick={() => taskId && approveMut.mutate(taskId)}
                  disabled={approveMut.isPending}
                >
                  {approveMut.isPending ? "Approving..." : "Approve"}
                </button>
                <button
                  className="review-btn review-btn-reject"
                  onClick={() => taskId && rejectMut.mutate(taskId)}
                  disabled={rejectMut.isPending}
                >
                  {rejectMut.isPending ? "Rejecting..." : "Reject"}
                </button>
              </>
            )}
            {showArchive && (
              <button
                className="review-btn review-btn-archive"
                onClick={() =>
                  taskId &&
                  archiveMut.mutate(taskId, {
                    onSuccess: () => showToast("Task archived", "success"),
                  })
                }
                disabled={archiveMut.isPending}
              >
                {archiveMut.isPending ? "Archiving..." : "Archive"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Review Panel */}
      {latestReview && (
        <div className="task-detail-section">
          <h2>Review</h2>
          <ReviewPanel reviews={reviews || []} />
        </div>
      )}

      {/* Events Timeline */}
      {events && events.length > 0 && (
        <div className="task-detail-section">
          <h2>Activity</h2>
          <div className="events-timeline">
            {events.map((event) => (
              <div key={event.id} className="event-item">
                <div className="event-dot" />
                <div className="event-content">
                  <span className="event-type">{event.type}</span>
                  <span className="event-time">
                    {new Date(event.created_at).toLocaleString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
