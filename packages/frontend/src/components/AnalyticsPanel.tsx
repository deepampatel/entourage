/**
 * Analytics visualization components — SVG charts and sortable tables.
 *
 * No external chart library — all charts are pure SVG for zero-dependency rendering.
 */

import { useState } from "react";
import type {
  AgentPerformance,
  CostTimeseriesPoint,
  MonthlyRollup,
} from "../api/types";

// ─── Cost Trend Bar Chart (SVG) ─────────────────────────────

interface CostTrendChartProps {
  data: CostTimeseriesPoint[];
}

export function CostTrendChart({ data }: CostTrendChartProps) {
  if (!data.length) {
    return <div className="analytics-empty">No cost data available</div>;
  }

  const maxCost = Math.max(...data.map((d) => d.cost_usd), 0.01);
  const chartWidth = 600;
  const chartHeight = 200;
  const barPadding = 2;
  const barWidth = Math.max(
    4,
    (chartWidth - barPadding * data.length) / data.length
  );

  return (
    <div className="analytics-chart-container">
      <svg
        viewBox={`0 0 ${chartWidth} ${chartHeight + 30}`}
        className="analytics-bar-chart"
      >
        {/* Y-axis labels */}
        <text x="0" y="12" className="chart-label">
          ${maxCost.toFixed(2)}
        </text>
        <text x="0" y={chartHeight - 2} className="chart-label">
          $0
        </text>

        {/* Grid line */}
        <line
          x1="40"
          y1={chartHeight}
          x2={chartWidth}
          y2={chartHeight}
          stroke="var(--border-default)"
          strokeWidth="1"
        />

        {/* Bars */}
        {data.map((point, i) => {
          const barHeight = (point.cost_usd / maxCost) * (chartHeight - 20);
          const x = 45 + i * (barWidth + barPadding);
          const y = chartHeight - barHeight;

          return (
            <g key={point.period}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barHeight}
                className="chart-bar"
                rx="2"
              >
                <title>
                  {point.period}: ${point.cost_usd.toFixed(4)} ({point.session_count} sessions)
                </title>
              </rect>
              {/* X-axis labels (every 5th) */}
              {(i % 5 === 0 || i === data.length - 1) && (
                <text
                  x={x + barWidth / 2}
                  y={chartHeight + 16}
                  textAnchor="middle"
                  className="chart-label-x"
                >
                  {point.period.slice(5)} {/* MM-DD */}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── Agent Efficiency Table ──────────────────────────────────

interface AgentEfficiencyTableProps {
  agents: AgentPerformance[];
}

type SortKey = keyof AgentPerformance;

export function AgentEfficiencyTable({ agents }: AgentEfficiencyTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("total_cost_usd");
  const [sortAsc, setSortAsc] = useState(false);

  if (!agents.length) {
    return <div className="analytics-empty">No agent data available</div>;
  }

  const sorted = [...agents].sort((a, b) => {
    const aVal = a[sortKey] ?? 0;
    const bVal = b[sortKey] ?? 0;
    if (typeof aVal === "string" && typeof bVal === "string") {
      return sortAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }
    return sortAsc
      ? (aVal as number) - (bVal as number)
      : (bVal as number) - (aVal as number);
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const arrow = (key: SortKey) =>
    sortKey === key ? (sortAsc ? " ↑" : " ↓") : "";

  return (
    <div className="analytics-table-wrapper">
      <table className="analytics-table">
        <thead>
          <tr>
            <th onClick={() => handleSort("agent_name")}>
              Agent{arrow("agent_name")}
            </th>
            <th onClick={() => handleSort("role")}>Role{arrow("role")}</th>
            <th onClick={() => handleSort("tasks_completed")}>
              Done{arrow("tasks_completed")}
            </th>
            <th onClick={() => handleSort("tasks_failed")}>
              Failed{arrow("tasks_failed")}
            </th>
            <th onClick={() => handleSort("total_cost_usd")}>
              Cost{arrow("total_cost_usd")}
            </th>
            <th onClick={() => handleSort("cache_hit_rate")}>
              Cache Hit{arrow("cache_hit_rate")}
            </th>
            <th onClick={() => handleSort("success_rate")}>
              Success{arrow("success_rate")}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((a) => (
            <tr key={a.agent_id}>
              <td className="agent-name-cell">{a.agent_name}</td>
              <td>
                <span className={`role-badge role-${a.role}`}>{a.role}</span>
              </td>
              <td>{a.tasks_completed}</td>
              <td>{a.tasks_failed}</td>
              <td>${a.total_cost_usd.toFixed(4)}</td>
              <td>{a.cache_hit_rate.toFixed(1)}%</td>
              <td>
                <span
                  className={
                    a.success_rate >= 80
                      ? "success-high"
                      : a.success_rate >= 50
                        ? "success-medium"
                        : "success-low"
                  }
                >
                  {a.success_rate.toFixed(0)}%
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Run Success Gauge ──────────────────────────────────

interface RunSuccessGaugeProps {
  rate: number;
  label: string;
}

export function RunSuccessGauge({ rate, label }: RunSuccessGaugeProps) {
  const radius = 45;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (rate / 100) * circumference;
  const color = rate >= 80 ? "var(--semantic-green)" : rate >= 50 ? "var(--semantic-orange)" : "var(--semantic-red)";

  return (
    <div className="analytics-gauge">
      <svg width="120" height="120" viewBox="0 0 120 120">
        {/* Background circle */}
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke="var(--border-default)"
          strokeWidth="8"
        />
        {/* Progress arc */}
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 60 60)"
        />
        {/* Value text */}
        <text
          x="60"
          y="55"
          textAnchor="middle"
          className="gauge-value"
          fill={color}
        >
          {rate.toFixed(0)}%
        </text>
        <text x="60" y="72" textAnchor="middle" className="gauge-label">
          {label}
        </text>
      </svg>
    </div>
  );
}

// ─── Monthly Rollup Table ────────────────────────────────────

interface MonthlyRollupTableProps {
  data: MonthlyRollup[];
}

export function MonthlyRollupTable({ data }: MonthlyRollupTableProps) {
  if (!data.length) {
    return <div className="analytics-empty">No monthly data available</div>;
  }

  return (
    <div className="analytics-table-wrapper">
      <table className="analytics-table">
        <thead>
          <tr>
            <th>Month</th>
            <th>Total Cost</th>
            <th>Sessions</th>
            <th>Tasks</th>
          </tr>
        </thead>
        <tbody>
          {[...data].reverse().map((m) => (
            <tr key={m.month}>
              <td>{m.month}</td>
              <td>${m.total_cost_usd.toFixed(4)}</td>
              <td>{m.total_sessions}</td>
              <td>{m.total_tasks}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Period Selector ─────────────────────────────────────────

interface PeriodSelectorProps {
  value: string;
  onChange: (period: string) => void;
}

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  const periods = [
    { key: "day", label: "24h" },
    { key: "week", label: "7d" },
    { key: "month", label: "30d" },
    { key: "all", label: "All" },
  ];

  return (
    <div className="period-selector">
      {periods.map((p) => (
        <button
          key={p.key}
          className={`period-btn ${value === p.key ? "period-btn-active" : ""}`}
          onClick={() => onChange(p.key)}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
