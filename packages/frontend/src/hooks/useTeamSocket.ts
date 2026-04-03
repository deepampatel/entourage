/**
 * WebSocket hook — real-time event streaming for a team.
 *
 * Learn: Connects to ws://host/ws/{teamId}, receives events from
 * Redis pub/sub, and patches TanStack Query cache for instant updates.
 * Auto-reconnects on disconnect with exponential backoff.
 */

import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

interface WSEvent {
  type: string;
  [key: string]: unknown;
}

// ─── Grouped notifications (batch within 3s window) ──

const pendingNotifications: { type: string; title: string }[] = [];
let notifyTimer: number | undefined;

function queueNotification(type: string, title: string) {
  pendingNotifications.push({ type, title });

  if (notifyTimer) clearTimeout(notifyTimer);
  notifyTimer = window.setTimeout(() => {
    if (Notification.permission !== "granted" || !pendingNotifications.length) {
      pendingNotifications.length = 0;
      return;
    }

    const completed = pendingNotifications.filter((n) => n.type === "completed");
    const failed = pendingNotifications.filter((n) => n.type === "failed");

    if (completed.length + failed.length === 1) {
      // Single notification
      const n = pendingNotifications[0];
      new Notification(
        n.type === "completed" ? "Run completed" : "Run failed",
        { body: n.title, icon: "/favicon.ico" }
      );
    } else {
      // Grouped notification
      const parts: string[] = [];
      if (completed.length) parts.push(`${completed.length} completed`);
      if (failed.length) parts.push(`${failed.length} failed`);
      new Notification(
        `${pendingNotifications.length} runs finished`,
        { body: parts.join(", "), icon: "/favicon.ico" }
      );
    }

    pendingNotifications.length = 0;
  }, 3000);
}

export function useTeamSocket(teamId: string | undefined) {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | undefined>(undefined);
  const reconnectDelayRef = useRef(1000);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const msg: WSEvent = JSON.parse(event.data);

        // Invalidate relevant queries based on event type
        switch (msg.type) {
          case "task.created":
          case "task.updated":
          case "task.status_changed":
          case "task.assigned":
            queryClient.invalidateQueries({ queryKey: ["tasks", teamId] });
            if (msg.task_id) {
              queryClient.invalidateQueries({
                queryKey: ["task", msg.task_id],
              });
            }
            break;

          case "session.started":
          case "session.ended":
          case "session.usage_recorded":
            queryClient.invalidateQueries({ queryKey: ["costs", teamId] });
            queryClient.invalidateQueries({ queryKey: ["agents", teamId] });
            break;

          case "agent.status_changed":
            queryClient.invalidateQueries({ queryKey: ["agents", teamId] });
            break;

          case "message.sent":
            queryClient.invalidateQueries({ queryKey: ["messages", teamId] });
            break;

          case "human_request.created":
          case "human_request.resolved":
          case "human_request.expired":
            queryClient.invalidateQueries({
              queryKey: ["human-requests", teamId],
            });
            break;

          case "review.requested":
          case "review.verdict":
          case "review.comment_added":
            queryClient.invalidateQueries({ queryKey: ["tasks", teamId] });
            if (msg.task_id) {
              queryClient.invalidateQueries({
                queryKey: ["reviews", msg.task_id],
              });
            }
            break;

          case "merge.started":
          case "merge.completed":
          case "merge.failed":
            queryClient.invalidateQueries({ queryKey: ["tasks", teamId] });
            break;

          case "agent.run_started":
          case "agent.run_completed":
          case "agent.run_failed":
            queryClient.invalidateQueries({ queryKey: ["agents", teamId] });
            queryClient.invalidateQueries({ queryKey: ["costs", teamId] });
            break;

          // Run lifecycle events — group notifications
          case "run.completed":
          case "run.failed":
            queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
            queryClient.invalidateQueries({ queryKey: ["run-tasks"] });
            queueNotification(
              msg.type === "run.completed" ? "completed" : "failed",
              (msg.title as string) || "A run"
            );
            break;

          case "run.task_completed":
          case "run.task_failed":
          case "run.task_started":
          case "run.task_retried":
            queryClient.invalidateQueries({ queryKey: ["runs", teamId] });
            queryClient.invalidateQueries({ queryKey: ["run-tasks"] });
            break;

          default:
            // Unknown event type — invalidate everything for safety
            queryClient.invalidateQueries({ queryKey: ["tasks", teamId] });
            queryClient.invalidateQueries({ queryKey: ["agents", teamId] });
        }
      } catch {
        // Ignore malformed messages
      }
    },
    [queryClient, teamId]
  );

  useEffect(() => {
    if (!teamId) return;

    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      // Include auth token if available (required in production)
      const token = localStorage.getItem("openclaw_token") || "";
      const tokenParam = token ? `?token=${token}` : "";
      const ws = new WebSocket(`${protocol}//${host}/ws/${teamId}${tokenParam}`);

      ws.onopen = () => {
        reconnectDelayRef.current = 1000; // Reset backoff on successful connect
      };

      ws.onmessage = handleMessage;

      ws.onclose = () => {
        // Auto-reconnect with exponential backoff
        reconnectTimerRef.current = window.setTimeout(() => {
          reconnectDelayRef.current = Math.min(
            reconnectDelayRef.current * 2,
            30000
          );
          connect();
        }, reconnectDelayRef.current);
      };

      ws.onerror = () => {
        ws.close();
      };

      wsRef.current = ws;
    }

    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [teamId, handleMessage]);
}
