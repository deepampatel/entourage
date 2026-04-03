"""Task service — business logic for task management with DAG-enforced state machine.

Learn: This is the CORE of the platform. Every task transition is:
1. Validated against VALID_TRANSITIONS (can't skip steps)
2. Checked against dependencies (can't start if deps aren't done)
3. Recorded as an immutable event (audit trail)
4. Applied to the task projection (the tasks table)

The state machine enforces the workflow:
  todo → in_progress → in_review → in_approval → merging → done → archived

Dependencies are enforced via depends_on (PostgreSQL INTEGER[]):
  Task B depends_on [Task A] → B can't move to in_progress until A is done.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import Agent, Message, Task
from openclaw.events.store import EventStore
from openclaw.events.types import (
    MESSAGE_SENT,
    TASK_ASSIGNED,
    TASK_CREATED,
    TASK_STATUS_CHANGED,
    TASK_UPDATED,
)


# ═══════════════════════════════════════════════════════════
# State Machine
# ═══════════════════════════════════════════════════════════

VALID_TRANSITIONS: dict[str, set[str]] = {
    "todo": {"in_progress", "cancelled"},
    "in_progress": {"in_review", "todo", "cancelled"},
    "in_review": {"in_approval", "in_progress", "cancelled"},
    "in_approval": {"merging", "in_progress", "cancelled"},
    "merging": {"done", "in_progress"},  # merge_failed → back to in_progress
    "done": {"archived"},
    "cancelled": {"archived"},
    "archived": set(),  # terminal state
}


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed."""
    pass


class DependencyBlockedError(Exception):
    """Raised when dependencies aren't resolved."""
    pass


# ═══════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════


class TaskService:
    """Business logic for task CRUD and state management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)

    # ─── Create ──────────────────────────────────────────

    async def create_task(
        self,
        team_id: uuid.UUID,
        title: str,
        description: str = "",
        priority: str = "medium",
        assignee_id: Optional[uuid.UUID] = None,
        dri_id: Optional[uuid.UUID] = None,
        depends_on: Optional[list[int]] = None,
        repo_ids: Optional[list[uuid.UUID]] = None,
        tags: Optional[list[str]] = None,
    ) -> Task:
        """Create a new task in 'todo' status.

        Learn: Tasks always start as 'todo'. The branch name is auto-generated
        from the task ID after flush (we need the auto-increment ID first).
        """
        task = Task(
            team_id=team_id,
            title=title,
            description=description,
            priority=priority,
            assignee_id=assignee_id,
            dri_id=dri_id,
            depends_on=depends_on or [],
            repo_ids=repo_ids or [],
            tags=tags or [],
        )
        self.db.add(task)
        await self.db.flush()  # get auto-generated ID

        # Auto-generate branch name: task-42-fix-login-bug
        slug = title.lower()[:50].replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        task.branch = f"task-{task.id}-{slug}"

        await self.events.append(
            stream_id=f"task:{task.id}",
            event_type=TASK_CREATED,
            data={
                "title": title,
                "priority": priority,
                "team_id": str(team_id),
                "assignee_id": str(assignee_id) if assignee_id else None,
                "depends_on": depends_on or [],
            },
        )

        await self.db.commit()
        return task

    # ─── Read ────────────────────────────────────────────

    async def get_task(self, task_id: int) -> Optional[Task]:
        result = await self.db.execute(
            select(Task).where(Task.id == task_id)
        )
        return result.scalars().first()

    async def list_tasks(
        self,
        team_id: uuid.UUID,
        status: Optional[str] = None,
        assignee_id: Optional[uuid.UUID] = None,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks with optional filters.

        Learn: Query filters are applied conditionally — only when the
        caller provides them. This keeps the API flexible.
        """
        query = (
            select(Task)
            .where(Task.team_id == team_id)
            .order_by(Task.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            query = query.where(Task.status == status)
        elif not include_archived:
            # Archived tasks are hidden by default in the main list view.
            query = query.where(Task.status != "archived")
        if assignee_id:
            query = query.where(Task.assignee_id == assignee_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ─── Update ──────────────────────────────────────────

    async def update_task(
        self,
        task_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[Task]:
        """Update task fields (NOT status — use change_status for that)."""
        task = await self.get_task(task_id)
        if not task:
            return None

        changes = {}
        if title is not None:
            task.title = title
            changes["title"] = title
        if description is not None:
            task.description = description
            changes["description"] = description
        if priority is not None:
            task.priority = priority
            changes["priority"] = priority
        if tags is not None:
            task.tags = tags
            changes["tags"] = tags

        if changes:
            await self.events.append(
                stream_id=f"task:{task_id}",
                event_type=TASK_UPDATED,
                data=changes,
            )

        await self.db.commit()
        return task

    # ─── Status changes (state machine) ──────────────────

    async def change_status(
        self,
        task_id: int,
        new_status: str,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Task:
        """Change task status with validation and dependency enforcement.

        Learn: This is where the state machine lives:
        1. Load task
        2. Validate: is this transition allowed?
        3. ENFORCE dependencies: can't start if deps aren't done
        4. Apply the change
        5. Record the event (immutable audit trail)

        Raises:
            InvalidTransitionError: if the transition isn't allowed
            DependencyBlockedError: if dependencies aren't resolved
        """
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        old_status = task.status

        # 1. Validate transition
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from '{old_status}' to '{new_status}'. "
                f"Allowed: {allowed or 'none (terminal state)'}"
            )

        # 2. Enforce dependencies when starting work
        if new_status == "in_progress" and task.depends_on:
            await self._check_dependencies(task.depends_on)

        # 3. Apply change
        task.status = new_status
        if new_status == "done":
            task.completed_at = datetime.now(timezone.utc)

        # 4. Record event
        await self.events.append(
            stream_id=f"task:{task_id}",
            event_type=TASK_STATUS_CHANGED,
            data={
                "from": old_status,
                "to": new_status,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )

        await self.db.commit()
        return task

    async def archive_task(
        self,
        task_id: int,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Task:
        """Archive a completed/cancelled task."""
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status not in {"done", "cancelled"}:
            raise InvalidTransitionError(
                "Only tasks in 'done' or 'cancelled' status can be archived"
            )
        return await self.change_status(
            task_id=task_id,
            new_status="archived",
            actor_id=actor_id,
        )

    async def _check_dependencies(self, dep_ids: list[int]) -> None:
        """Verify all dependency tasks are 'done'.

        Learn: DAG enforcement — this is what prevents tasks from starting
        before their prerequisites are complete. It's a simple query:
        count how many deps are NOT done. If any, block.
        """
        result = await self.db.execute(
            select(Task.id, Task.status)
            .where(Task.id.in_(dep_ids))
        )
        deps = {row.id: row.status for row in result}

        # Check for missing deps (IDs that don't exist)
        missing = set(dep_ids) - set(deps.keys())
        if missing:
            raise DependencyBlockedError(
                f"Dependency tasks not found: {missing}"
            )

        # Check for unresolved deps
        blocked = {tid: status for tid, status in deps.items() if status != "done"}
        if blocked:
            raise DependencyBlockedError(
                f"Blocked by unresolved dependencies: "
                + ", ".join(f"task {tid} ({s})" for tid, s in blocked.items())
            )

    # ─── Assignment ──────────────────────────────────────

    async def assign_task(
        self,
        task_id: int,
        assignee_id: uuid.UUID,
    ) -> Optional[Task]:
        """Assign an agent to a task."""
        task = await self.get_task(task_id)
        if not task:
            return None

        old_assignee = task.assignee_id
        task.assignee_id = assignee_id

        await self.events.append(
            stream_id=f"task:{task_id}",
            event_type=TASK_ASSIGNED,
            data={
                "from": str(old_assignee) if old_assignee else None,
                "to": str(assignee_id),
            },
        )

        await self.db.commit()
        return task

    # ─── Dependent Tasks ─────────────────────────────────

    async def get_dependent_tasks(self, task_id: int) -> list[dict]:
        """Get information about tasks that this task depends on.

        Returns a list of dicts with id, title, and status for each dependent task.
        """
        task = await self.get_task(task_id)
        if not task or not task.depends_on:
            return []

        result = await self.db.execute(
            select(Task.id, Task.title, Task.status)
            .where(Task.id.in_(task.depends_on))
        )

        dependent_tasks = [
            {"id": row.id, "title": row.title, "status": row.status}
            for row in result
        ]

        return dependent_tasks


class MessageService:
    """Business logic for inter-agent messaging."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)

    async def send_message(
        self,
        team_id: uuid.UUID,
        sender_id: uuid.UUID,
        sender_type: str,
        recipient_id: uuid.UUID,
        recipient_type: str,
        content: str,
        task_id: Optional[int] = None,
    ) -> Message:
        """Send a message between agents or users.

        Learn: Messages are the decoupled communication layer.
        Instead of agents calling each other directly, they send messages.
        The dispatcher (Phase 6) watches for unprocessed messages
        and triggers agent turns when new messages arrive.
        """
        msg = Message(
            team_id=team_id,
            sender_id=sender_id,
            sender_type=sender_type,
            recipient_id=recipient_id,
            recipient_type=recipient_type,
            task_id=task_id,
            content=content,
        )
        self.db.add(msg)
        await self.db.flush()

        await self.events.append(
            stream_id=f"message:{msg.id}",
            event_type=MESSAGE_SENT,
            data={
                "sender_id": str(sender_id),
                "sender_type": sender_type,
                "recipient_id": str(recipient_id),
                "recipient_type": recipient_type,
                "task_id": task_id,
            },
        )

        await self.db.commit()
        return msg

    async def get_inbox(
        self,
        recipient_id: uuid.UUID,
        unprocessed_only: bool = True,
        limit: int = 50,
    ) -> list[Message]:
        """Get messages for a recipient (agent's inbox).

        Learn: The inbox is how agents know they have work to do.
        unprocessed_only=True returns only messages the agent hasn't
        handled yet — this is what the dispatcher uses.
        """
        query = (
            select(Message)
            .where(Message.recipient_id == recipient_id)
            .order_by(Message.id.desc())
            .limit(limit)
        )
        if unprocessed_only:
            query = query.where(Message.processed_at.is_(None))

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def mark_processed(self, message_id: int) -> None:
        """Mark a message as processed by the recipient."""
        await self.db.execute(
            update(Message)
            .where(Message.id == message_id)
            .values(processed_at=datetime.now(timezone.utc))
        )
        await self.db.commit()
