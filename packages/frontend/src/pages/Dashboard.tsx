/**
 * Dashboard page — overview of team activity, stats, agents, and pending requests.
 *
 * Learn: Enhanced from basic overview to include:
 * - Pending human requests section with inline respond forms
 * - Agent cards with current task and run button
 * - Stats row with pending request count
 */

import { AgentCard } from "../components/AgentCard";
import { HumanRequestCard } from "../components/HumanRequestCard";
import { SkeletonGrid, SkeletonList } from "../components/Skeleton";
import { StatCard } from "../components/StatCard";
import { TaskCard } from "../components/TaskCard";
import {
  useAcknowledgeAlert,
  useAgents,
  useAlerts,
  useCosts,
  useHumanRequests,
  useRespondToRequest,
  useRunAgent,
  useTasks,
} from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";

interface DashboardProps {
  teamId: string;
}

export function Dashboard({ teamId }: DashboardProps) {
  // Real-time updates via WebSocket
  useTeamSocket(teamId);

  const { data: tasks, isLoading: tasksLoading } = useTasks(teamId);
  const { data: agents, isLoading: agentsLoading } = useAgents(teamId);
  const { data: costs } = useCosts(teamId);
  const { data: pendingRequests } = useHumanRequests(teamId, "pending");
  const { data: alerts } = useAlerts(teamId, false);
  const respondMutation = useRespondToRequest(teamId);
  const runAgentMutation = useRunAgent(teamId);
  const acknowledgeMutation = useAcknowledgeAlert(teamId);

  const activeTasks = tasks?.filter(
    (t) => !["done", "cancelled"].includes(t.status)
  );
  const workingAgents = agents?.filter((a) => a.status === "working");

  const handleRespond = (requestId: number, response: string) => {
    respondMutation.mutate({ requestId, response });
  };

  const handleRunAgent = (agentId: string) => {
    runAgentMutation.mutate({ agentId });
  };

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>

      {/* Active Alerts Banner */}
      {alerts && alerts.length > 0 && (
        <div className="alerts-banner">
          {alerts.map((alert) => (
            <div
              key={alert.id}
              className={`alert-item alert-${alert.severity}`}
            >
              <span className="alert-severity">
                {alert.severity === "critical" ? "!!!" : "!"}
              </span>
              <span className="alert-message">{alert.message}</span>
              <button
                className="alert-dismiss"
                onClick={() => acknowledgeMutation.mutate(alert.id)}
                disabled={acknowledgeMutation.isPending}
              >
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Stats Row */}
      <div className="stats-row">
        <StatCard
          label="Active Tasks"
          value={activeTasks?.length ?? 0}
        />
        <StatCard
          label="Working Agents"
          value={`${workingAgents?.length ?? 0} / ${agents?.length ?? 0}`}
        />
        <StatCard
          label="Pending Requests"
          value={pendingRequests?.length ?? 0}
          color={pendingRequests?.length ? "#f59e0b" : undefined}
        />
        <StatCard
          label="Cost (7d)"
          value={`$${(costs?.total_cost_usd ?? 0).toFixed(2)}`}
        />
      </div>

      {/* Pending Human Requests */}
      {pendingRequests && pendingRequests.length > 0 && (
        <section className="dashboard-section">
          <h2>Pending Requests</h2>
          <div className="hr-list">
            {pendingRequests.map((req) => (
              <HumanRequestCard
                key={req.id}
                request={req}
                agents={agents}
                onRespond={handleRespond}
                isResponding={respondMutation.isPending}
              />
            ))}
          </div>
        </section>
      )}

      {/* Agents Section */}
      <section className="dashboard-section">
        <h2>Agents</h2>
        {agentsLoading ? (
          <SkeletonGrid count={4} />
        ) : (
          <div className="agent-grid">
            {agents?.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                tasks={tasks}
                onRunAgent={handleRunAgent}
                isRunning={runAgentMutation.isPending}
              />
            ))}
            {agents?.length === 0 && (
              <p className="empty-state">No agents configured</p>
            )}
          </div>
        )}
      </section>

      {/* Active Tasks Section */}
      <section className="dashboard-section">
        <h2>Active Tasks</h2>
        {tasksLoading ? (
          <SkeletonList count={3} />
        ) : (
          <div className="task-list">
            {activeTasks?.map((task) => (
              <TaskCard key={task.id} task={task} agents={agents} />
            ))}
            {activeTasks?.length === 0 && (
              <p className="empty-state">No active tasks</p>
            )}
          </div>
        )}
      </section>

      {/* Cost Breakdown */}
      {costs && costs.per_agent.length > 0 && (
        <section className="dashboard-section">
          <h2>Cost Breakdown (7d)</h2>
          <div className="cost-table">
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Sessions</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                {costs.per_agent.map((a) => (
                  <tr key={a.agent_id}>
                    <td>{a.agent_name}</td>
                    <td>{a.sessions}</td>
                    <td>${a.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
