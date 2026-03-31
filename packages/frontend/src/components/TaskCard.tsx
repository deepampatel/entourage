/**
 * Task card — shows task title, status, priority, assignee, and review badge.
 *
 * Learn: Enhanced to show review verdict badge inline when the task has
 * an associated review. Clicking could expand to show review details
 * (future enhancement).
 */

import { Link } from "react-router-dom";
import type { Agent, Review, Task } from "../api/types";
import { PRIORITY_COLORS, STATUS_LABELS, type Priority, type TaskStatus } from "../api/types";

interface TaskCardProps {
  task: Task;
  agents?: Agent[];
  review?: Review;
}

const VERDICT_BADGE: Record<string, { label: string; className: string }> = {
  approve: { label: "Approved", className: "review-badge-approved" },
  reject: { label: "Rejected", className: "review-badge-rejected" },
  request_changes: { label: "Changes", className: "review-badge-changes" },
};

export function TaskCard({ task, agents, review }: TaskCardProps) {
  const assignee = agents?.find((a) => a.id === task.assignee_id);
  const statusLabel = STATUS_LABELS[task.status as TaskStatus] || task.status;
  const priorityColor = PRIORITY_COLORS[task.priority as Priority] || "var(--semantic-gray)";

  const verdictInfo = review?.verdict
    ? VERDICT_BADGE[review.verdict]
    : null;

  return (
    <div className="task-card">
      <div className="task-header">
        <span className="task-id">#{task.id}</span>
        <div className="task-header-right">
          {/* Review badge */}
          {review && (
            <span
              className={`review-badge ${
                verdictInfo?.className || "review-badge-pending"
              }`}
            >
              {verdictInfo?.label || "In Review"}
            </span>
          )}
          <span
            className="task-priority"
            style={{ color: priorityColor }}
          >
            {task.priority}
          </span>
        </div>
      </div>
      <Link to={`/tasks/${task.id}`} className="task-title" style={{ color: "inherit", textDecoration: "none" }}>
        {task.title}
      </Link>
      <div className="task-footer">
        <span className={`task-status task-status-${task.status}`}>
          {statusLabel}
        </span>
        {assignee && (
          <span className="task-assignee">{assignee.name}</span>
        )}
      </div>
      {task.tags.length > 0 && (
        <div className="task-tags">
          {task.tags.map((tag) => (
            <span key={tag} className="task-tag">{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}
