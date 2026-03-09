"""SQLAlchemy ORM models — single source of truth for the database schema.

Learn: Declarative ORM mapping with SQLAlchemy 2.0 style (Mapped[] + mapped_column).
Each class = one table. Relationships, constraints, and indexes defined here.
Alembic auto-generates migrations by comparing these models to the actual DB.

Key concepts:
- UUID primary keys (better for distributed systems than auto-increment)
- JSONB for flexible config (replaces Delegate's JSON-as-TEXT hack)
- Proper PostgreSQL ARRAY columns (replaces Delegate's JSON string arrays)
- server_default for DB-level defaults (work even for raw SQL inserts)
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ══════════════════════════════════════════════════════════════
# Phase 1: Organizations, Teams, Users, Agents, Repos
# ══════════════════════════════════════════════════════════════


class Organization(Base):
    """Multi-tenant root. Each org has teams, and teams have agents.

    Learn: This is the top-level tenant boundary. All data is scoped
    to an org. Row-level security in Phase 9 will filter by org_id.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    # Relationships
    teams: Mapped[list["Team"]] = relationship(back_populates="organization")


class Team(Base):
    """A team within an organization. Teams have agents and repos.

    Learn: Teams scope work — each team has its own tasks, agents, and repos.
    Unlike Delegate's filesystem-based teams, this is DB-driven.
    """

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_teams_org_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # team settings: budget limits, model prefs, workflow config
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="teams")
    agents: Mapped[list["Agent"]] = relationship(back_populates="team")
    repositories: Mapped[list["Repository"]] = relationship(back_populates="team")


class User(Base):
    """A human user. Can be a member of multiple teams.

    Learn: Users are the human side of the system. They log in,
    approve tasks, answer agent questions, and review code.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # nullable for OAuth
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TeamMember(Base):
    """Team membership — links users to teams with roles.

    Learn: Many-to-many with a role attribute. A user can be in
    multiple teams with different roles (owner, admin, member).
    """

    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member"
    )  # owner, admin, member


class Agent(Base):
    """An AI agent within a team.

    Learn: Agents are DB-driven (not filesystem-discovered like Delegate).
    Each agent has a role (manager/engineer), model preference, and
    JSON config for token budgets, tool restrictions, etc.
    """

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_agents_team_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="engineer"
    )  # manager, engineer, reviewer
    model: Mapped[str] = mapped_column(
        String(50), nullable=False, default="claude-sonnet-4-20250514"
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # token_budget, allowed_tools, etc.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="idle"
    )  # idle, working, paused
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    team: Mapped["Team"] = relationship(back_populates="agents")


class Repository(Base):
    """A git repository registered with a team.

    Learn: Repos are registered (not auto-discovered). Each repo
    has config for approval mode, test commands, etc.
    """

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_repos_team_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(
        String(100), nullable=False, default="main"
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # approval_mode, test_cmd, setup_cmd
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    team: Mapped["Team"] = relationship(back_populates="repositories")


# ══════════════════════════════════════════════════════════════
# Phase 1: Event sourcing foundation + Sessions
# ══════════════════════════════════════════════════════════════


class Event(Base):
    """Immutable event log — the foundation of event sourcing.

    Learn: Every state change in the system is recorded as an event.
    Events are append-only (never updated/deleted). The events table
    is the source of truth; other tables are "projections" (caches).

    stream_id examples: "task:42", "agent:<uuid>", "team:<uuid>"
    type examples: "task.created", "task.status_changed", "agent.turn_started"
    """

    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_stream", "stream_id", "id"),
        Index("idx_events_type", "type"),
        Index("idx_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )  # actor_id, correlation_id, causation_id
    # Note: Python attr is "meta" because "metadata" is reserved by SQLAlchemy.
    # DB column is still "metadata" via the first positional arg.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Session(Base):
    """Agent work session — tracks a single agent turn.

    Learn: Every time an agent runs (reads inbox, thinks, uses tools),
    that's a "session." We track tokens, cost, duration for budgeting.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cache_read: Mapped[int] = mapped_column(Integer, default=0)
    cache_write: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ══════════════════════════════════════════════════════════════
# Phase 2: Tasks + Messages
# ══════════════════════════════════════════════════════════════


class Task(Base):
    """A unit of work — the central entity of the platform.

    Learn: Tasks flow through a DAG-enforced state machine:
      todo → in_progress → in_review → in_approval → merging → done
    Each transition is validated (can't skip steps) and dependency-checked
    (can't start if depends_on tasks aren't done).

    Key columns:
    - depends_on: PostgreSQL INTEGER[] — tasks that must complete before this starts
    - repo_ids: UUID[] — which repos this task touches
    - tags: TEXT[] — flexible categorization
    - branch: auto-generated from task ID for worktrees (Phase 3)
    """

    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_team_status", "team_id", "status"),
        Index("idx_tasks_assignee", "assignee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="todo"
    )  # todo, in_progress, in_review, in_approval, merging, done, cancelled
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, default="medium"
    )  # low, medium, high, critical

    # Who owns + who's assigned
    dri_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )  # directly responsible individual (manager)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )  # who's working on it (engineer)

    # DAG dependencies — proper PostgreSQL ARRAY, not JSON string
    depends_on: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{}"
    )

    # Repos this task touches
    repo_ids: Mapped[Optional[list[uuid.UUID]]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default="{}"
    )

    # Flexible metadata
    tags: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    branch: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    task_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )  # Python attr is task_metadata; DB column is "metadata"

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    team: Mapped["Team"] = relationship()
    dri: Mapped[Optional["Agent"]] = relationship(foreign_keys=[dri_id])
    assignee: Mapped[Optional["Agent"]] = relationship(foreign_keys=[assignee_id])


class Message(Base):
    """Inter-agent message — the inbox/outbox system.

    Learn: Agents communicate via messages (not direct function calls).
    This decouples agents and creates an auditable communication trail.
    The dispatcher (Phase 6) monitors unprocessed messages to trigger
    agent turns.

    sender_type + recipient_type: "agent" or "user"
    This allows both agent↔agent and human↔agent communication.
    """

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_recipient", "recipient_id", "processed_at"),
        Index("idx_messages_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "agent" or "user"
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    recipient_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "agent" or "user"
    task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Delivery tracking
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ══════════════════════════════════════════════════════════════
# Phase 7: Human-in-the-loop
# ══════════════════════════════════════════════════════════════


class HumanRequest(Base):
    """An agent's request for human input — question, approval, or review.

    Learn: This is the bridge between AI agents and human oversight.
    When an agent needs a decision, it creates a HumanRequest. The UI
    shows it as a notification. The human responds via REST or WebSocket.
    The dispatcher detects the resolution and continues the agent's work.

    Kinds:
    - 'question': Agent needs information (free-text answer)
    - 'approval': Agent needs yes/no approval to proceed
    - 'review': Agent needs a code/work review

    All persistent — survives server restarts (unlike Delegate's in-memory state).
    """

    __tablename__ = "human_requests"
    __table_args__ = (
        Index("idx_human_requests_team_status", "team_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # question, approval, review
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )  # pre-defined answer options (for approval: ["approve", "reject"])
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending, resolved, expired
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )  # user UUID who responded
    timeout_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ══════════════════════════════════════════════════════════════
# Phase 8: Code Review + Merge
# ══════════════════════════════════════════════════════════════


class Review(Base):
    """A code review for a task.

    Learn: When a task moves to 'in_review', a review is created.
    Reviewers (human or AI) examine the diff, leave comments,
    and render a verdict: approve, request_changes, or reject.

    Multiple review attempts are tracked via the 'attempt' field.
    Each attempt is a fresh review cycle.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt", name="uq_reviews_task_attempt"),
        Index("idx_reviews_task", "task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reviewer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )  # user or agent UUID who reviewed
    reviewer_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="user"
    )  # "user" or "agent"
    verdict: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # approve, request_changes, reject (null = pending)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    comments: Mapped[list["ReviewComment"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class ReviewComment(Base):
    """A comment on a specific file/line in a code review.

    Learn: Review comments are anchored to a file path and optionally
    a line number. This mirrors GitHub PR review comments.
    """

    __tablename__ = "review_comments"
    __table_args__ = (
        Index("idx_review_comments_review", "review_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reviews.id"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    author_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "user" or "agent"
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    review: Mapped["Review"] = relationship(back_populates="comments")


class MergeJob(Base):
    """A merge job queued for background processing.

    Learn: When a task is approved, a merge job is created and
    pushed to the Redis merge queue. The merge worker picks it
    up, rebases, runs tests, and merges. The result is recorded
    here for auditability.

    Statuses: queued → running → success / failed
    """

    __tablename__ = "merge_jobs"
    __table_args__ = (
        Index("idx_merge_jobs_task", "task_id"),
        Index("idx_merge_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )  # queued, running, success, failed
    strategy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="rebase"
    )  # rebase, merge, squash
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    merge_commit: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )  # SHA of merge commit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ══════════════════════════════════════════════════════════════
# Phase 9: API Keys
# ══════════════════════════════════════════════════════════════


class ApiKey(Base):
    """API key for programmatic access (MCP agents, CI, etc.).

    Learn: API keys authenticate OpenClaw agents and external systems.
    The key itself is only shown once (on creation). We store the hash
    and a prefix for identification.

    Scopes control what the key can do:
    - 'all': full access
    - 'read': read-only
    - 'agent': agent operations only
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("idx_api_keys_org", "org_id"),
        Index("idx_api_keys_prefix", "prefix"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # e.g. "oc_abc123"
    scopes: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{all}"
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ══════════════════════════════════════════════════════════════
# Phase 10: Webhooks + Settings
# ══════════════════════════════════════════════════════════════


class Webhook(Base):
    """Incoming webhook configuration — receives events from GitHub, etc.

    Learn: Webhooks let external systems push events into OpenClaw.
    When GitHub sends a push/PR/issue event, we match it to a team
    and create or update tasks accordingly.

    The secret is used to verify HMAC signatures on incoming payloads.
    """

    __tablename__ = "webhooks"
    __table_args__ = (
        Index("idx_webhooks_org", "org_id"),
        Index("idx_webhooks_team", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=True
    )  # null = org-wide
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="github"
    )  # github, gitlab, bitbucket, custom
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    events: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{push,pull_request}"
    )  # event types to listen for
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )  # extra provider-specific config
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )


class WebhookDelivery(Base):
    """Log of incoming webhook deliveries — audit trail.

    Learn: Every incoming webhook POST is logged here for debugging
    and audit purposes. The payload is stored (minus sensitive data)
    along with the processing result.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("idx_webhook_deliveries_webhook", "webhook_id"),
        Index("idx_webhook_deliveries_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("webhooks.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # push, pull_request, issues, etc.
    payload: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # incoming payload (sanitized)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="received"
    )  # received, processed, failed, ignored
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ══════════════════════════════════════════════════════════════
# Phase 12: Pipelines
# ══════════════════════════════════════════════════════════════


class Pipeline(Base):
    """A pipeline — the top-level orchestration unit.

    A pipeline takes a human intent ("Add OAuth2 login"), uses an LLM
    planner to decompose it into a TaskGraph, gets human approval, then
    executes tasks serially (or in parallel in future phases).

    State machine:
      draft → planning → awaiting_plan_approval → executing →
      reviewing → merging → done
    With: paused, failed, cancelled as escape states.
    """

    __tablename__ = "pipelines"
    __table_args__ = (
        Index("idx_pipelines_team_status", "team_id", "status"),
        Index("idx_pipelines_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    repository_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=True
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="draft"
    )  # draft, planning, awaiting_plan_approval, executing,
    #    reviewing, merging, done, paused, failed, cancelled
    task_graph: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), default=0
    )
    actual_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), default=0
    )
    budget_limit_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False, default=10.0
    )
    branch_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    pr_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pipeline_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    contract_set: Mapped[Optional[dict]] = mapped_column(
        "contracts", JSONB, nullable=True
    )  # Phase 2: Raw ContractSet from ContractBuilder
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    team: Mapped["Team"] = relationship()
    pipeline_tasks: Mapped[list["PipelineTask"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )
    contracts: Mapped[list["Contract"]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )
    budget_ledger: Mapped[Optional["BudgetLedger"]] = relationship(
        back_populates="pipeline", uselist=False, cascade="all, delete-orphan"
    )


class PipelineTask(Base):
    """A task within a pipeline's TaskGraph.

    Separate from the standalone Task model — PipelineTasks are
    scoped to a pipeline and managed by the ExecutionLoop.
    """

    __tablename__ = "pipeline_tasks"
    __table_args__ = (
        Index("idx_ptasks_pipeline", "pipeline_id"),
        Index("idx_ptasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    complexity: Mapped[str] = mapped_column(
        String(5), nullable=False, default="M"
    )  # S, M, L, XL
    assigned_role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="engineer"
    )  # engineer, reviewer
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="todo"
    )  # todo, blocked, in_progress, awaiting_review, done, failed
    dependencies: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{}"
    )
    integration_hints: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    estimated_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    branch_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default=""
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(back_populates="pipeline_tasks")


class Contract(Base):
    """A typed interface contract between pipeline tasks.

    Phase 2: When tasks run in parallel, contracts prevent interface
    collisions. The ContractBuilder LLM generates these from the TaskGraph,
    and agents must acknowledge (lock) contracts before starting work.

    Contract types:
      - api: Function/endpoint signatures
      - type: Shared data type definitions
      - event: Async event schemas
      - database: Shared table/column definitions
    """

    __tablename__ = "contracts"
    __table_args__ = (
        Index("idx_contracts_pipeline", "pipeline_id"),
        Index("idx_contracts_type", "contract_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    pipeline_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("pipeline_tasks.id"), nullable=True
    )
    contract_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # api, type, event, database
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    specification: Mapped[dict] = mapped_column(JSONB, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(back_populates="contracts")


class BudgetLedger(Base):
    """Per-pipeline budget tracking.

    Each pipeline gets one ledger. As agents work, cost entries are
    recorded and the running total is updated. Warnings at 80%,
    hard stop at 100%.
    """

    __tablename__ = "budget_ledgers"
    __table_args__ = (
        Index("idx_budget_ledgers_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    budget_limit_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), nullable=False
    )
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), default=0
    )
    actual_cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), default=0
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ok"
    )  # ok, warn, exceeded
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=utcnow
    )

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(back_populates="budget_ledger")
    entries: Mapped[list["BudgetEntry"]] = relationship(
        back_populates="ledger", cascade="all, delete-orphan"
    )


class BudgetEntry(Base):
    """Individual cost entry within a pipeline's budget ledger."""

    __tablename__ = "budget_entries"
    __table_args__ = (
        Index("idx_budget_entries_pipeline", "pipeline_id"),
        Index("idx_budget_entries_recorded", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ledger_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("budget_ledgers.id", ondelete="CASCADE"),
        nullable=False,
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    pipeline_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("pipeline_tasks.id"), nullable=True
    )
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    ledger: Mapped["BudgetLedger"] = relationship(back_populates="entries")


# ══════════════════════════════════════════════════════════════
# Phase 3C: Alerts
# ══════════════════════════════════════════════════════════════


class Alert(Base):
    """Persistent alert record for budget, failure, and performance events.

    Learn: Alerts are created by AlertService.evaluate_all() and deduplicated
    within a 1-hour window. Users can acknowledge alerts to dismiss them
    from the dashboard without deleting the record.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_team_acknowledged", "team_id", "acknowledged"),
        Index("idx_alerts_kind_created", "kind", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    alert_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ══════════════════════════════════════════════════════════════
# Phase 3B: Sandbox test runs
# ══════════════════════════════════════════════════════════════


class SandboxRun(Base):
    """A sandboxed test execution for a pipeline task.

    Learn: After a pipeline task completes, the SandboxManager can run
    tests in a Docker container. The result (pass/fail, stdout/stderr)
    is stored here for auditability. If tests fail, the task may be
    retried automatically.
    """

    __tablename__ = "sandbox_runs"
    __table_args__ = (
        Index("idx_sandbox_runs_pipeline_task", "pipeline_task_id"),
        Index("idx_sandbox_runs_team", "team_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sandbox_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    pipeline_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=True
    )
    pipeline_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("pipeline_tasks.id"), nullable=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    test_cmd: Mapped[str] = mapped_column(Text, nullable=False)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_seconds: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0)
    image: Mapped[str] = mapped_column(
        String(200), nullable=False, default="python:3.12-slim"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ══════════════════════════════════════════════════════════════
# Phase 3D: Security audit log
# ══════════════════════════════════════════════════════════════


class SecurityAudit(Base):
    """Audit log entry for security-relevant agent actions.

    Learn: The SecurityEnforcer records every violation (blocked or
    logged) here. This provides a tamper-evident trail for security
    reviews and compliance — who tried what, when, and what rule
    matched.
    """

    __tablename__ = "security_audit"
    __table_args__ = (
        Index("idx_security_audit_team_created", "team_id", "created_at"),
        Index("idx_security_audit_agent_created", "agent_id", "created_at"),
        Index("idx_security_audit_kind", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    pipeline_task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("pipeline_tasks.id"), nullable=True
    )
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
