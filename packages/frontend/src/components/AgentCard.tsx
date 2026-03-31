/**
 * Agent card — shows agent name, role, status, current task, and run button.
 *
 * Learn: Enhanced from basic status display to include:
 * - Current task title when agent is working
 * - "Run Agent" button when idle (dispatches via API)
 * - Adapter info from config
 */

import type { Agent, Task } from "../api/types";

interface AgentCardProps {
  agent: Agent;
  tasks?: Task[];
  onRunAgent?: (agentId: string) => void;
  isRunning?: boolean;
}

const STATUS_COLORS: Record<string, string> = {
  idle: "var(--semantic-gray)",
  working: "var(--semantic-green)",
  paused: "var(--semantic-orange)",
  error: "var(--semantic-red)",
};

export function AgentCard({ agent, tasks, onRunAgent, isRunning }: AgentCardProps) {
  const currentTask = tasks?.find(
    (t) => t.assignee_id === agent.id && t.status === "in_progress"
  );
  const adapter = (agent.config?.adapter as string) || "default";

  return (
    <div className="agent-card">
      <div className="agent-header">
        <span
          className="agent-status-dot"
          style={{ backgroundColor: STATUS_COLORS[agent.status] || "var(--semantic-gray)" }}
        />
        <span className="agent-name">{agent.name}</span>
      </div>
      <div className="agent-meta">
        <span className="agent-role">{agent.role}</span>
        <span className="agent-model">{agent.model.split("-").slice(0, 2).join(" ")}</span>
        <span className="agent-adapter">{adapter}</span>
      </div>
      <div className="agent-status-text">{agent.status}</div>

      {/* Show current task when working */}
      {currentTask && (
        <div className="agent-current-task">
          working on: Task #{currentTask.id} &mdash;{" "}
          {currentTask.title.slice(0, 50)}
          {currentTask.title.length > 50 ? "..." : ""}
        </div>
      )}

      {/* Run button when idle */}
      {agent.status === "idle" && agent.role === "engineer" && onRunAgent && (
        <button
          className="agent-run-btn"
          onClick={() => onRunAgent(agent.id)}
          disabled={isRunning}
        >
          {isRunning ? "Starting..." : "Run Agent"}
        </button>
      )}
    </div>
  );
}
