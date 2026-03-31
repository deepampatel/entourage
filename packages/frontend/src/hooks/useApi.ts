/**
 * TanStack Query hooks — typed data fetching for all API endpoints.
 *
 * Learn: Each hook wraps a TanStack useQuery/useMutation call.
 * The query key determines caching and invalidation. WebSocket
 * events trigger invalidation via useTeamSocket.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type {
  Agent,
  AgentPerformance,
  Alert,
  Contract,
  CostSummary,
  CostTimeseriesPoint,
  HumanRequest,
  MonthlyRollup,
  Org,
  Repository,
  Run,
  RunMetrics,
  RunTask,
  Review,
  SandboxRun,
  Task,
  TaskEvent,
  Team,
} from "../api/types";

// ─── Organizations ─────────────────────────────────────

export function useOrgs() {
  return useQuery({
    queryKey: ["orgs"],
    queryFn: () => apiClient.get<Org[]>("/api/v1/orgs"),
  });
}

export function useCreateOrg() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; slug: string }) =>
      apiClient.post<Org>("/api/v1/orgs", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["orgs"] });
    },
  });
}

// ─── Teams ─────────────────────────────────────────────

export function useTeams(orgId: string | undefined) {
  return useQuery({
    queryKey: ["teams", orgId],
    queryFn: () => apiClient.get<Team[]>(`/api/v1/orgs/${orgId}/teams`),
    enabled: !!orgId,
  });
}

export function useCreateTeam(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; slug: string }) =>
      apiClient.post<Team>(`/api/v1/orgs/${orgId}/teams`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teams", orgId] });
    },
  });
}

// ─── Create Agent ─────────────────────────────────────

export function useCreateAgent(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      role: string;
      model: string;
      config?: Record<string, unknown>;
    }) => apiClient.post<Agent>(`/api/v1/teams/${teamId}/agents`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents", teamId] });
    },
  });
}

// ─── Agents ────────────────────────────────────────────

export function useAgents(teamId: string | undefined) {
  return useQuery({
    queryKey: ["agents", teamId],
    queryFn: () => apiClient.get<Agent[]>(`/api/v1/teams/${teamId}/agents`),
    enabled: !!teamId,
    refetchInterval: 10_000,
  });
}

// ─── Repositories ─────────────────────────────────────

export function useRepos(teamId: string | undefined) {
  return useQuery({
    queryKey: ["repos", teamId],
    queryFn: () => apiClient.get<Repository[]>(`/api/v1/teams/${teamId}/repos`),
    enabled: !!teamId,
  });
}

export function useRegisterRepo(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      local_path: string;
      default_branch?: string;
    }) =>
      apiClient.post<Repository>(`/api/v1/teams/${teamId}/repos`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repos", teamId] });
    },
  });
}

// ─── Tasks ─────────────────────────────────────────────

export function useTasks(
  teamId: string | undefined,
  filters?: { status?: string; assignee_id?: string }
) {
  return useQuery({
    queryKey: ["tasks", teamId, filters],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (filters?.status) params.status = filters.status;
      if (filters?.assignee_id) params.assignee_id = filters.assignee_id;
      return apiClient.get<Task[]>(`/api/v1/teams/${teamId}/tasks`, params);
    },
    enabled: !!teamId,
    refetchInterval: 15_000,
  });
}

export function useTask(taskId: number | undefined) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => apiClient.get<Task>(`/api/v1/tasks/${taskId}`),
    enabled: !!taskId,
  });
}

// ─── Costs ─────────────────────────────────────────────

export function useCosts(teamId: string | undefined, days: number = 7) {
  return useQuery({
    queryKey: ["costs", teamId, days],
    queryFn: () =>
      apiClient.get<CostSummary>(`/api/v1/teams/${teamId}/costs`, {
        days: String(days),
      }),
    enabled: !!teamId,
    refetchInterval: 30_000,
  });
}

// ─── Human Requests ────────────────────────────────────

export function useHumanRequests(
  teamId: string | undefined,
  status?: string
) {
  return useQuery({
    queryKey: ["human-requests", teamId, status],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      return apiClient.get<HumanRequest[]>(
        `/api/v1/teams/${teamId}/human-requests`,
        params
      );
    },
    enabled: !!teamId,
    refetchInterval: 10_000,
  });
}

// ─── Reviews ───────────────────────────────────────────

export function useTaskReviews(taskId: number | undefined) {
  return useQuery({
    queryKey: ["reviews", taskId],
    queryFn: () => apiClient.get<Review[]>(`/api/v1/tasks/${taskId}/reviews`),
    enabled: !!taskId,
  });
}

// ─── Mutations ─────────────────────────────────────────

export function useRespondToRequest(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      requestId,
      response,
    }: {
      requestId: number;
      response: string;
    }) =>
      apiClient.post<HumanRequest>(
        `/api/v1/human-requests/${requestId}/respond`,
        { response }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["human-requests", teamId],
      });
    },
  });
}

export function useApproveTask(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: number) =>
      apiClient.post<Review>(`/api/v1/tasks/${taskId}/approve`, {}),
    onSuccess: (_, taskId) => {
      queryClient.invalidateQueries({ queryKey: ["tasks", teamId] });
      queryClient.invalidateQueries({ queryKey: ["reviews", taskId] });
    },
  });
}

export function useRejectTask(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: number) =>
      apiClient.post<Review>(`/api/v1/tasks/${taskId}/reject`, {}),
    onSuccess: (_, taskId) => {
      queryClient.invalidateQueries({ queryKey: ["tasks", teamId] });
      queryClient.invalidateQueries({ queryKey: ["reviews", taskId] });
    },
  });
}

// ─── Task Events ──────────────────────────────────────

export function useTaskEvents(taskId: number | undefined) {
  return useQuery({
    queryKey: ["task-events", taskId],
    queryFn: () =>
      apiClient.get<TaskEvent[]>(`/api/v1/tasks/${taskId}/events`),
    enabled: !!taskId,
  });
}

// ─── Team Settings ────────────────────────────────────

export interface TeamSettings {
  team_id: string;
  team_name: string;
  settings: Record<string, unknown>;
}

export function useTeamSettings(teamId: string | undefined) {
  return useQuery({
    queryKey: ["team-settings", teamId],
    queryFn: () =>
      apiClient.get<TeamSettings>(`/api/v1/settings/teams/${teamId}`),
    enabled: !!teamId,
  });
}

export function useUpdateTeamSettings(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: Record<string, unknown>) =>
      apiClient.patch<TeamSettings>(
        `/api/v1/settings/teams/${teamId}`,
        settings
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["team-settings", teamId],
      });
    },
  });
}

// ─── Agent Run ────────────────────────────────────────

export function useRunAgent(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      agentId,
      taskId,
    }: {
      agentId: string;
      taskId?: number;
    }) =>
      apiClient.post(`/api/v1/agents/${agentId}/run`, { task_id: taskId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents", teamId] });
    },
  });
}

// ─── Runs ─────────────────────────────────────────────

export function useRuns(
  teamId: string | undefined,
  status?: string
) {
  return useQuery({
    queryKey: ["runs", teamId, status],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      return apiClient.get<Run[]>(
        `/api/v1/teams/${teamId}/runs`,
        params
      );
    },
    enabled: !!teamId,
    refetchInterval: 10_000,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () =>
      apiClient.get<Run>(`/api/v1/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: 5_000,
  });
}

export function useRunTasks(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-tasks", runId],
    queryFn: () =>
      apiClient.get<RunTask[]>(
        `/api/v1/runs/${runId}/tasks`
      ),
    enabled: !!runId,
    refetchInterval: 10_000,
  });
}

export function useCreateRun(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      title: string;
      intent: string;
      budget_limit_usd?: number;
      repository_id?: string;
      template?: string;
    }) =>
      apiClient.post<Run>(
        `/api/v1/teams/${teamId}/runs`,
        body
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
    },
  });
}

export function useStartRun(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiClient.post<Run>(
        `/api/v1/runs/${runId}/start`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
    },
  });
}

export function useApprovePlan(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiClient.post<Run>(
        `/api/v1/runs/${runId}/approve-plan`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
    },
  });
}

export function useRejectPlan(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      feedback,
    }: {
      runId: string;
      feedback?: string;
    }) =>
      apiClient.post<Run>(
        `/api/v1/runs/${runId}/reject-plan`,
        { feedback }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
    },
  });
}

// ─── Contract hooks ──────────────────────────────────────

export function useRunContracts(runId: string | undefined) {
  return useQuery({
    queryKey: ["run-contracts", runId],
    queryFn: () =>
      apiClient.get<Contract[]>(
        `/api/v1/runs/${runId}/contracts`
      ),
    enabled: !!runId,
    refetchInterval: 10_000,
  });
}

export function useGenerateContracts(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiClient.post<Run>(
        `/api/v1/runs/${runId}/generate-contracts`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
    },
  });
}

// ─── Analytics ────────────────────────────────────────

export function useRunMetrics(
  teamId: string | undefined,
  period: string = "week"
) {
  return useQuery({
    queryKey: ["analytics-run-metrics", teamId, period],
    queryFn: () =>
      apiClient.get<RunMetrics>(
        `/api/v1/analytics/${teamId}/runs`,
        { period }
      ),
    enabled: !!teamId,
    refetchInterval: 30_000,
  });
}

export function useAgentPerformance(
  teamId: string | undefined,
  period: string = "week"
) {
  return useQuery({
    queryKey: ["analytics-agent-performance", teamId, period],
    queryFn: () =>
      apiClient.get<AgentPerformance[]>(
        `/api/v1/analytics/${teamId}/agents`,
        { period }
      ),
    enabled: !!teamId,
    refetchInterval: 30_000,
  });
}

export function useCostTimeseries(
  teamId: string | undefined,
  granularity: string = "day",
  days: number = 30
) {
  return useQuery({
    queryKey: ["analytics-cost-timeseries", teamId, granularity, days],
    queryFn: () =>
      apiClient.get<CostTimeseriesPoint[]>(
        `/api/v1/analytics/${teamId}/costs`,
        { granularity, days: String(days) }
      ),
    enabled: !!teamId,
    refetchInterval: 60_000,
  });
}

export function useMonthlyRollup(
  teamId: string | undefined,
  months: number = 6
) {
  return useQuery({
    queryKey: ["analytics-monthly-rollup", teamId, months],
    queryFn: () =>
      apiClient.get<MonthlyRollup[]>(
        `/api/v1/analytics/${teamId}/costs/monthly`,
        { months: String(months) }
      ),
    enabled: !!teamId,
    refetchInterval: 60_000,
  });
}

// ─── Sandbox ──────────────────────────────────────────

export function useSandboxRuns(
  runId: string | undefined,
  taskId: number | undefined
) {
  return useQuery({
    queryKey: ["sandbox-runs", runId, taskId],
    queryFn: () =>
      apiClient.get<SandboxRun[]>(
        `/api/v1/runs/${runId}/tasks/${taskId}/sandbox-runs`
      ),
    enabled: !!runId && !!taskId,
    refetchInterval: 10_000,
  });
}

export function useTriggerSandboxRun(_teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      taskId,
      testCmd,
      image,
      setupCmd,
    }: {
      runId: string;
      taskId: number;
      testCmd: string;
      image?: string;
      setupCmd?: string;
    }) =>
      apiClient.post<SandboxRun>(
        `/api/v1/runs/${runId}/tasks/${taskId}/sandbox-runs`,
        {
          test_cmd: testCmd,
          image: image || "python:3.12-slim",
          setup_cmd: setupCmd,
        }
      ),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({
        queryKey: ["sandbox-runs", vars.runId, vars.taskId],
      });
    },
  });
}

// ─── Alerts ─────────────────────────────────────────────

export function useAlerts(teamId: string | undefined, acknowledged?: boolean) {
  const params = new URLSearchParams();
  if (acknowledged !== undefined) params.set("acknowledged", String(acknowledged));
  const qs = params.toString();
  return useQuery({
    queryKey: ["alerts", teamId, acknowledged],
    queryFn: () =>
      apiClient.get<Alert[]>(
        `/api/v1/teams/${teamId}/alerts${qs ? `?${qs}` : ""}`
      ),
    enabled: !!teamId,
    refetchInterval: 30_000,
  });
}

export function useAcknowledgeAlert(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: number) =>
      apiClient.post<Alert>(
        `/api/v1/teams/${teamId}/alerts/${alertId}/acknowledge`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts", teamId] });
    },
  });
}
