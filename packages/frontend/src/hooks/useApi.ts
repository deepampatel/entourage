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
  CostSummary,
  HumanRequest,
  Org,
  Pipeline,
  PipelineTask,
  Review,
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

// ─── Pipelines ────────────────────────────────────────

export function usePipelines(
  teamId: string | undefined,
  status?: string
) {
  return useQuery({
    queryKey: ["pipelines", teamId, status],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      return apiClient.get<Pipeline[]>(
        `/api/v1/teams/${teamId}/pipelines`,
        params
      );
    },
    enabled: !!teamId,
    refetchInterval: 10_000,
  });
}

export function usePipeline(pipelineId: string | undefined) {
  return useQuery({
    queryKey: ["pipeline", pipelineId],
    queryFn: () =>
      apiClient.get<Pipeline>(`/api/v1/pipelines/${pipelineId}`),
    enabled: !!pipelineId,
    refetchInterval: 5_000,
  });
}

export function usePipelineTasks(pipelineId: string | undefined) {
  return useQuery({
    queryKey: ["pipeline-tasks", pipelineId],
    queryFn: () =>
      apiClient.get<PipelineTask[]>(
        `/api/v1/pipelines/${pipelineId}/tasks`
      ),
    enabled: !!pipelineId,
    refetchInterval: 10_000,
  });
}

export function useCreatePipeline(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      title: string;
      intent: string;
      budget_limit_usd?: number;
    }) =>
      apiClient.post<Pipeline>(
        `/api/v1/teams/${teamId}/pipelines`,
        body
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipelines", teamId] });
    },
  });
}

export function useStartPipeline(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pipelineId: string) =>
      apiClient.post<Pipeline>(
        `/api/v1/pipelines/${pipelineId}/start`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipelines", teamId] });
    },
  });
}

export function useApprovePlan(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pipelineId: string) =>
      apiClient.post<Pipeline>(
        `/api/v1/pipelines/${pipelineId}/approve-plan`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipelines", teamId] });
    },
  });
}

export function useRejectPlan(teamId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      pipelineId,
      feedback,
    }: {
      pipelineId: string;
      feedback?: string;
    }) =>
      apiClient.post<Pipeline>(
        `/api/v1/pipelines/${pipelineId}/reject-plan`,
        { feedback }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipelines", teamId] });
    },
  });
}
