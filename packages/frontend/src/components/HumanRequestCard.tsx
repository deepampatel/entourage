/**
 * HumanRequestCard — shows a human-in-the-loop request with inline respond form.
 *
 * Learn: Agents can ask questions, request approvals, or request reviews.
 * This card displays the request details and lets the user respond inline.
 * Pending requests show a text input + submit button. Resolved/expired
 * requests show the response or expired status.
 */

import { useState } from "react";
import type { Agent, HumanRequest } from "../api/types";

interface HumanRequestCardProps {
  request: HumanRequest;
  agents?: Agent[];
  onRespond?: (requestId: number, response: string) => void;
  isResponding?: boolean;
}

const KIND_LABELS: Record<string, string> = {
  question: "Question",
  approval: "Approval",
  review: "Review",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "var(--semantic-orange)",
  resolved: "var(--semantic-green)",
  expired: "var(--semantic-red)",
};

export function HumanRequestCard({
  request,
  agents,
  onRespond,
  isResponding,
}: HumanRequestCardProps) {
  const [responseText, setResponseText] = useState("");
  const agent = agents?.find((a) => a.id === request.agent_id);
  const isPending = request.status === "pending";

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (responseText.trim() && onRespond) {
      onRespond(request.id, responseText.trim());
      setResponseText("");
    }
  };

  const handleOptionClick = (option: string) => {
    if (onRespond) {
      onRespond(request.id, option);
    }
  };

  const timeAgo = (dateStr: string) => {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  return (
    <div className={`hr-card hr-card-${request.status}`}>
      <div className="hr-header">
        <span className="hr-id">#{request.id}</span>
        <span
          className="hr-kind"
          style={{ color: STATUS_COLORS[request.status] }}
        >
          {KIND_LABELS[request.kind] || request.kind}
        </span>
        <span className="hr-status" style={{ color: STATUS_COLORS[request.status] }}>
          {request.status}
        </span>
      </div>

      <div className="hr-question">{request.question}</div>

      <div className="hr-meta">
        {agent && <span className="hr-agent">from {agent.name}</span>}
        {request.task_id && (
          <span className="hr-task">task #{request.task_id}</span>
        )}
        <span className="hr-time">{timeAgo(request.created_at)}</span>
      </div>

      {/* Options buttons for approval-type requests */}
      {isPending && request.options.length > 0 && (
        <div className="hr-options">
          {request.options.map((opt) => (
            <button
              key={opt}
              className="hr-option-btn"
              onClick={() => handleOptionClick(opt)}
              disabled={isResponding}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {/* Free-text response form */}
      {isPending && request.options.length === 0 && (
        <form className="hr-respond-form" onSubmit={handleSubmit}>
          <input
            type="text"
            className="hr-respond-input"
            placeholder="Type your response..."
            value={responseText}
            onChange={(e) => setResponseText(e.target.value)}
            disabled={isResponding}
          />
          <button
            type="submit"
            className="hr-respond-btn"
            disabled={!responseText.trim() || isResponding}
          >
            {isResponding ? "..." : "Send"}
          </button>
        </form>
      )}

      {/* Resolved response */}
      {request.response && (
        <div className="hr-response">
          <span className="hr-response-label">Response:</span> {request.response}
        </div>
      )}
    </div>
  );
}
