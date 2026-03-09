"""Event type constants.

Learn: Centralizing event types as constants prevents typos and
makes it easy to discover all event types in the system.
Each phase adds its own event types here.
"""

# ─── Phase 1: Team/Agent/Repo lifecycle ──────────────────

TEAM_CREATED = "team.created"
AGENT_CREATED = "agent.created"
AGENT_STATUS_CHANGED = "agent.status_changed"
REPO_REGISTERED = "repo.registered"

# ─── Phase 2: Task lifecycle ─────────────────────────────

TASK_CREATED = "task.created"
TASK_UPDATED = "task.updated"
TASK_STATUS_CHANGED = "task.status_changed"
TASK_ASSIGNED = "task.assigned"
TASK_COMMENT_ADDED = "task.comment_added"
MESSAGE_SENT = "message.sent"

# ─── Phase 4: Agent execution ────────────────────────────

SESSION_STARTED = "session.started"
SESSION_ENDED = "session.ended"
SESSION_USAGE_RECORDED = "session.usage_recorded"
AGENT_BUDGET_EXCEEDED = "agent.budget_exceeded"

# ─── Phase 7: Human-in-the-loop ──────────────────────────

HUMAN_REQUEST_CREATED = "human_request.created"
HUMAN_REQUEST_RESOLVED = "human_request.resolved"
HUMAN_REQUEST_EXPIRED = "human_request.expired"

# ─── Phase 8: Code review + merge ──────────────────────

REVIEW_CREATED = "review.created"
REVIEW_VERDICT = "review.verdict"
REVIEW_COMMENT_ADDED = "review.comment_added"
REVIEW_FEEDBACK_SENT = "review.feedback_sent"
MERGE_QUEUED = "merge.queued"
MERGE_STARTED = "merge.started"
MERGE_COMPLETED = "merge.completed"
MERGE_FAILED = "merge.failed"

# ─── Phase 10: Webhooks + settings ──────────────────────

WEBHOOK_CREATED = "webhook.created"
WEBHOOK_UPDATED = "webhook.updated"
WEBHOOK_DELETED = "webhook.deleted"
WEBHOOK_DELIVERY_RECEIVED = "webhook.delivery_received"
WEBHOOK_DELIVERY_PROCESSED = "webhook.delivery_processed"
WEBHOOK_DELIVERY_FAILED = "webhook.delivery_failed"
SETTINGS_UPDATED = "settings.updated"

# ─── PR / Push events ────────────────────────────────────

PR_CREATED = "pr.created"
PR_PUSH_COMPLETED = "pr.push_completed"
PR_PUSH_FAILED = "pr.push_failed"

# ─── Phase 11: Agent adapter runs ───────────────────────

AGENT_RUN_STARTED = "agent.run_started"
AGENT_RUN_COMPLETED = "agent.run_completed"
AGENT_RUN_FAILED = "agent.run_failed"
AGENT_RUN_TIMEOUT = "agent.run_timeout"

# ─── Phase 12: Pipeline lifecycle ─────────────────────────

PIPELINE_CREATED = "pipeline.created"
PIPELINE_STATUS_CHANGED = "pipeline.status_changed"
PIPELINE_PLAN_GENERATED = "pipeline.plan_generated"
PIPELINE_PLAN_APPROVED = "pipeline.plan_approved"
PIPELINE_PLAN_REJECTED = "pipeline.plan_rejected"
PIPELINE_TASK_STARTED = "pipeline.task_started"
PIPELINE_TASK_COMPLETED = "pipeline.task_completed"
PIPELINE_TASK_FAILED = "pipeline.task_failed"
PIPELINE_BUDGET_WARNING = "pipeline.budget_warning"
PIPELINE_BUDGET_EXCEEDED = "pipeline.budget_exceeded"
PIPELINE_COMPLETED = "pipeline.completed"
PIPELINE_FAILED = "pipeline.failed"

# ─── Phase 2A: Contract lifecycle ──────────────────────────

PIPELINE_CONTRACTS_GENERATED = "pipeline.contracts_generated"
PIPELINE_CONTRACT_LOCKED = "pipeline.contract_locked"

# ─── Phase 2D: Resume / Retry ─────────────────────────────

PIPELINE_TASK_RETRIED = "pipeline.task_retried"
PIPELINE_RESUMED = "pipeline.resumed"

# ─── Phase 3B: Sandbox ───────────────────────────────────

SANDBOX_STARTED = "sandbox.started"
SANDBOX_PASSED = "sandbox.passed"
SANDBOX_FAILED = "sandbox.failed"
SANDBOX_TIMEOUT = "sandbox.timeout"
SANDBOX_ERROR = "sandbox.error"

# ─── Phase 3C: Alerts ──────────────────────────────────

ALERT_BUDGET_WARNING = "alert.budget_warning"
ALERT_BUDGET_EXCEEDED = "alert.budget_exceeded"
ALERT_FAILURE_SPIKE = "alert.failure_spike"
ALERT_PERFORMANCE = "alert.performance_degradation"
ALERT_ACKNOWLEDGED = "alert.acknowledged"

# ─── Phase 3D: Security ─────────────────────────────────

SECURITY_VIOLATION_BLOCKED = "security.violation.blocked"
SECURITY_VIOLATION_LOGGED = "security.violation.logged"
