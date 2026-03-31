/**
 * ReviewPanel — shows review status and approve/reject controls for a task.
 *
 * Learn: Tasks in in_review or in_approval status may have reviews attached.
 * This panel shows the review verdict, comments, and action buttons.
 */

import type { Review } from "../api/types";

interface ReviewPanelProps {
  reviews: Review[];
  onApprove?: () => void;
  onReject?: () => void;
  isSubmitting?: boolean;
}

const VERDICT_COLORS: Record<string, string> = {
  approve: "var(--semantic-green)",
  reject: "var(--semantic-red)",
  request_changes: "var(--semantic-orange)",
};

const VERDICT_LABELS: Record<string, string> = {
  approve: "Approved",
  reject: "Rejected",
  request_changes: "Changes Requested",
};

export function ReviewPanel({
  reviews,
  onApprove,
  onReject,
  isSubmitting,
}: ReviewPanelProps) {
  if (!reviews.length) return null;

  const latest = reviews[0]; // Newest first from API
  const hasPendingVerdict = latest.verdict === null;

  return (
    <div className="review-panel">
      <div className="review-header">
        <span className="review-title">Review #{latest.id}</span>
        {latest.verdict ? (
          <span
            className="review-verdict"
            style={{ color: VERDICT_COLORS[latest.verdict] }}
          >
            {VERDICT_LABELS[latest.verdict] || latest.verdict}
          </span>
        ) : (
          <span className="review-verdict review-pending">Pending</span>
        )}
      </div>

      {latest.summary && (
        <div className="review-summary">{latest.summary}</div>
      )}

      {/* Review comments */}
      {latest.comments.length > 0 && (
        <div className="review-comments">
          {latest.comments.map((c) => (
            <div key={c.id} className="review-comment">
              {c.file_path && (
                <span className="review-comment-file">
                  {c.file_path}
                  {c.line_number ? `:${c.line_number}` : ""}
                </span>
              )}
              <span className="review-comment-text">{c.content}</span>
            </div>
          ))}
        </div>
      )}

      {/* Approve / Reject buttons */}
      {hasPendingVerdict && (onApprove || onReject) && (
        <div className="review-actions">
          {onApprove && (
            <button
              className="review-btn review-btn-approve"
              onClick={onApprove}
              disabled={isSubmitting}
            >
              Approve
            </button>
          )}
          {onReject && (
            <button
              className="review-btn review-btn-reject"
              onClick={onReject}
              disabled={isSubmitting}
            >
              Reject
            </button>
          )}
        </div>
      )}
    </div>
  );
}
