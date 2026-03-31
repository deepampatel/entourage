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
} from "../hooks/useApi";
import { ReviewPanel } from "../components/ReviewPanel";
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
      {showApproveReject && (
        <div className="task-detail-section">
          <h2>Actions</h2>
          <div className="review-actions">
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
