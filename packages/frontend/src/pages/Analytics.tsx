/**
 * Analytics page — run metrics, cost trends, agent efficiency, and monthly rollup.
 *
 * Learn: All chart components are pure SVG (no external chart library).
 * Data is fetched via TanStack Query hooks with auto-refresh.
 */

import { useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  CostTrendChart,
  AgentEfficiencyTable,
  RunSuccessGauge,
  MonthlyRollupTable,
  PeriodSelector,
} from "../components/AnalyticsPanel";
import {
  useRunMetrics,
  useAgentPerformance,
  useCostTimeseries,
  useMonthlyRollup,
} from "../hooks/useApi";
import { useTeamSocket } from "../hooks/useTeamSocket";

interface AnalyticsProps {
  teamId: string;
}

export function Analytics({ teamId }: AnalyticsProps) {
  const [period, setPeriod] = useState("week");

  // Real-time updates
  useTeamSocket(teamId);

  // Data hooks
  const { data: metrics, isLoading: metricsLoading } = useRunMetrics(
    teamId,
    period
  );
  const { data: agents, isLoading: agentsLoading } = useAgentPerformance(
    teamId,
    period
  );
  const { data: costData, isLoading: costLoading } = useCostTimeseries(
    teamId,
    "day",
    30
  );
  const { data: monthlyData } = useMonthlyRollup(teamId, 6);

  const isLoading = metricsLoading || agentsLoading || costLoading;

  return (
    <div className="analytics-page">
      <div className="analytics-header">
        <h1>Analytics</h1>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {/* Metric Cards Row */}
      <div className="stats-row">
        <StatCard
          label="Total Runs"
          value={metrics?.total_runs ?? 0}
        />
        <StatCard
          label="Success Rate"
          value={`${(metrics?.success_rate ?? 0).toFixed(0)}%`}
          color={
            (metrics?.success_rate ?? 0) >= 80
              ? "var(--semantic-green)"
              : (metrics?.success_rate ?? 0) >= 50
                ? "var(--semantic-orange)"
                : "var(--semantic-red)"
          }
        />
        <StatCard
          label="Total Cost"
          value={`$${(metrics?.total_cost_usd ?? 0).toFixed(2)}`}
        />
        <StatCard
          label="Avg Cost / Run"
          value={`$${(metrics?.avg_cost_usd ?? 0).toFixed(4)}`}
        />
      </div>

      {/* Success Gauges */}
      {metrics && !isLoading && (
        <section className="analytics-section">
          <h2>Run Health</h2>
          <div className="analytics-gauge-row">
            <RunSuccessGauge
              rate={metrics.success_rate}
              label="Success"
            />
            <div className="analytics-status-grid">
              <div className="status-stat">
                <span className="status-stat-value status-completed">
                  {metrics.completed}
                </span>
                <span className="status-stat-label">Completed</span>
              </div>
              <div className="status-stat">
                <span className="status-stat-value status-failed">
                  {metrics.failed}
                </span>
                <span className="status-stat-label">Failed</span>
              </div>
              <div className="status-stat">
                <span className="status-stat-value status-cancelled">
                  {metrics.cancelled}
                </span>
                <span className="status-stat-label">Cancelled</span>
              </div>
              <div className="status-stat">
                <span className="status-stat-value status-in-progress">
                  {metrics.in_progress}
                </span>
                <span className="status-stat-label">In Progress</span>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Cost Trend Chart */}
      <section className="analytics-section">
        <h2>Cost Trend (30 days)</h2>
        {costLoading ? (
          <div className="analytics-loading">Loading cost data...</div>
        ) : (
          <CostTrendChart data={costData ?? []} />
        )}
      </section>

      {/* Agent Efficiency Table */}
      <section className="analytics-section">
        <h2>Agent Efficiency</h2>
        {agentsLoading ? (
          <div className="analytics-loading">Loading agent data...</div>
        ) : (
          <AgentEfficiencyTable agents={agents ?? []} />
        )}
      </section>

      {/* Monthly Rollup */}
      <section className="analytics-section">
        <h2>Monthly Summary</h2>
        <MonthlyRollupTable data={monthlyData ?? []} />
      </section>
    </div>
  );
}
