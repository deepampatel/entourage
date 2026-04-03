"""Task and Message API routes.

Learn: These routes are the HTTP interface to the task state machine.
The service layer handles all validation (transitions, dependencies).
Routes just translate HTTP to service calls and handle error responses.

Key patterns:
- POST for creation and state changes (not idempotent)
- PATCH for partial updates (idempotent)
- Query params for filtering (status, assignee_id)
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import get_db
from openclaw.db.models import Task
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

from openclaw.schemas.task import (
    DependentTaskInfo,
    MessageCreate,
    MessageRead,
    StatusChange,
    TaskAssign,
    TaskCreate,
    TaskDetail,
    TaskListItem,
    TaskRead,
    TaskUpdate,
)
from openclaw.services.task_service import (
    DependencyBlockedError,
    InvalidTransitionError,
    MessageService,
    TaskService,
)

router = APIRouter()


def _task_svc(db: AsyncSession = Depends(get_db)) -> TaskService:
    return TaskService(db)


def _msg_svc(db: AsyncSession = Depends(get_db)) -> MessageService:
    return MessageService(db)


# ═══════════════════════════════════════════════════════════
# Tasks
# ═══════════════════════════════════════════════════════════


@router.post("/teams/{team_id}/tasks", response_model=TaskRead, status_code=201)
async def create_task(
    team_id: uuid.UUID,
    body: TaskCreate,
    svc: TaskService = Depends(_task_svc),
):
    """Create a new task in 'todo' status."""
    task = await svc.create_task(
        team_id=team_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        assignee_id=body.assignee_id,
        dri_id=body.dri_id,
        depends_on=body.depends_on,
        repo_ids=body.repo_ids,
        tags=body.tags,
    )
    return task


@router.get("/teams/{team_id}/tasks", response_model=list[TaskListItem])
async def list_tasks(
    team_id: uuid.UUID,
    status: Optional[str] = Query(None, description="Filter by status"),
    assignee_id: Optional[uuid.UUID] = Query(None, description="Filter by assignee"),
    include_archived: bool = Query(
        False,
        description="Include archived tasks in results when no status filter is set",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    svc: TaskService = Depends(_task_svc),
):
    """List tasks for a team with optional filters and dependent task information."""
    tasks = await svc.list_tasks(
        team_id=team_id,
        status=status,
        assignee_id=assignee_id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )

    # Enrich each task with dependent task information
    result = []
    for task in tasks:
        dependent_tasks_data = await svc.get_dependent_tasks(task.id)
        task_dict = {
            "id": task.id,
            "team_id": task.team_id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "dri_id": task.dri_id,
            "assignee_id": task.assignee_id,
            "depends_on": task.depends_on,
            "dependent_tasks": dependent_tasks_data,
            "repo_ids": task.repo_ids,
            "tags": task.tags,
            "branch": task.branch,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "completed_at": task.completed_at,
        }
        result.append(TaskListItem(**task_dict))

    return result


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: int,
    svc: TaskService = Depends(_task_svc),
):
    """Get a single task by ID with dependent task information."""
    task = await svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Fetch dependent task information
    dependent_tasks_data = await svc.get_dependent_tasks(task_id)

    # Convert to TaskDetail schema
    task_dict = {
        "id": task.id,
        "team_id": task.team_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "dri_id": task.dri_id,
        "assignee_id": task.assignee_id,
        "depends_on": task.depends_on,
        "dependent_tasks": dependent_tasks_data,
        "repo_ids": task.repo_ids,
        "tags": task.tags,
        "branch": task.branch,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
    }

    return TaskDetail(**task_dict)


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    svc: TaskService = Depends(_task_svc),
):
    """Partially update a task (title, description, priority, tags)."""
    task = await svc.update_task(
        task_id=task_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        tags=body.tags,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/status", response_model=TaskRead)
async def change_task_status(
    task_id: int,
    body: StatusChange,
    svc: TaskService = Depends(_task_svc),
):
    """Change task status. Validates transitions and enforces dependencies.

    Learn: This is the most important endpoint — it's the entry point
    to the DAG-enforced state machine. Returns 409 for invalid transitions
    or blocked dependencies (not 400, because the request is well-formed
    but conflicts with the current state).
    """
    try:
        task = await svc.change_status(
            task_id=task_id,
            new_status=body.status,
            actor_id=body.actor_id,
        )
        return task
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DependencyBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))


class ArchiveTaskRequest(BaseModel):
    """Optional actor metadata for archive action."""
    actor_id: Optional[uuid.UUID] = None


@router.post("/tasks/{task_id}/archive", response_model=TaskRead)
async def archive_task(
    task_id: int,
    body: Optional[ArchiveTaskRequest] = None,
    svc: TaskService = Depends(_task_svc),
):
    """Archive a task that is already done or cancelled."""
    try:
        task = await svc.archive_task(
            task_id=task_id,
            actor_id=body.actor_id if body else None,
        )
        return task
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/tasks/{task_id}/assign", response_model=TaskRead)
async def assign_task(
    task_id: int,
    body: TaskAssign,
    svc: TaskService = Depends(_task_svc),
):
    """Assign an agent to a task."""
    task = await svc.assign_task(task_id=task_id, assignee_id=body.assignee_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ═══════════════════════════════════════════════════════════
# Batch Task Creation (Multi-Agent Orchestration)
# ═══════════════════════════════════════════════════════════


class BatchTaskItem(BaseModel):
    """A single task in a batch create request."""

    title: str
    description: str = ""
    priority: str = "medium"
    assignee_id: Optional[str] = None
    depends_on_indices: list[int] = Field(
        default_factory=list,
        description="Indices (0-based) of other tasks in this batch that this task depends on",
    )
    tags: list[str] = Field(default_factory=list)


class BatchTaskRequest(BaseModel):
    """Batch task creation request."""

    tasks: list[BatchTaskItem]


@router.post("/teams/{team_id}/tasks/batch", response_model=list[TaskRead], status_code=201)
async def create_tasks_batch(
    team_id: uuid.UUID,
    body: BatchTaskRequest,
    svc: TaskService = Depends(_task_svc),
):
    """Create multiple tasks at once with inter-batch dependencies.

    Learn: Manager agents use this to break down work into parallel or
    sequential sub-tasks. depends_on_indices references positions (0-based)
    in the batch array, which are resolved to real task IDs after creation.
    """
    created_tasks: list = []
    for i, item in enumerate(body.tasks):
        # Resolve depends_on_indices to real task IDs
        depends_on = []
        for idx in item.depends_on_indices:
            if idx < 0 or idx >= len(created_tasks):
                raise HTTPException(
                    status_code=422,
                    detail=f"Task {i}: depends_on_indices[{idx}] out of range",
                )
            depends_on.append(created_tasks[idx].id)

        task = await svc.create_task(
            team_id=team_id,
            title=item.title,
            description=item.description,
            priority=item.priority,
            assignee_id=item.assignee_id,
            depends_on=depends_on,
            tags=item.tags,
        )
        created_tasks.append(task)

    return created_tasks


# ═══════════════════════════════════════════════════════════
# Task Events (read-only event sourcing query)
# ═══════════════════════════════════════════════════════════


@router.get("/tasks/{task_id}/events")
async def get_task_events(
    task_id: int,
    svc: TaskService = Depends(_task_svc),
):
    """Get the event history for a task (immutable audit trail).

    Learn: This is the power of event sourcing — every state change
    is recorded. You can see exactly what happened, when, and who did it.
    """
    events = await svc.events.read_stream(f"task:{task_id}")
    return [
        {
            "id": e.id,
            "type": e.type,
            "data": e.data,
            "metadata": e.meta,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


# ═══════════════════════════════════════════════════════════
# Messages
# ═══════════════════════════════════════════════════════════


@router.post("/teams/{team_id}/messages", response_model=MessageRead, status_code=201)
async def send_message(
    team_id: uuid.UUID,
    body: MessageCreate,
    svc: MessageService = Depends(_msg_svc),
):
    """Send a message between agents or users."""
    return await svc.send_message(
        team_id=team_id,
        sender_id=body.sender_id,
        sender_type=body.sender_type,
        recipient_id=body.recipient_id,
        recipient_type=body.recipient_type,
        task_id=body.task_id,
        content=body.content,
    )


@router.get("/agents/{agent_id}/inbox", response_model=list[MessageRead])
async def get_inbox(
    agent_id: uuid.UUID,
    unprocessed_only: bool = Query(True, description="Only show unprocessed messages"),
    limit: int = Query(50, ge=1, le=200),
    svc: MessageService = Depends(_msg_svc),
):
    """Get an agent's inbox (messages addressed to them)."""
    return await svc.get_inbox(
        recipient_id=agent_id,
        unprocessed_only=unprocessed_only,
        limit=limit,
    )


# ═══════════════════════════════════════════════════════════
# Context Carryover
# ═══════════════════════════════════════════════════════════


class ContextSave(BaseModel):
    """Save a key-value pair to task context."""

    key: str = Field(..., description="Context key (e.g. 'root_cause', 'architecture_decision')")
    value: str = Field(..., description="Context value")


@router.post("/tasks/{task_id}/context")
async def save_context(
    task_id: int,
    body: ContextSave,
    db: AsyncSession = Depends(get_db),
):
    """Save a key-value pair to task context (persists across agent runs).

    Learn: Context carryover lets agents save discoveries (root cause, key files,
    architecture decisions) so they don't start cold on re-dispatch. Stored in
    task_metadata.context JSONB.
    """
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    metadata = task.task_metadata or {}
    context = metadata.get("context", {})
    context[body.key] = body.value
    task.task_metadata = {**metadata, "context": context}
    flag_modified(task, "task_metadata")
    await db.commit()
    return {"key": body.key, "value": body.value, "saved": True}


@router.get("/tasks/{task_id}/context")
async def get_context(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all saved context for a task.

    Returns the context dict from task_metadata, or empty dict if none.
    """
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    metadata = task.task_metadata or {}
    return {"task_id": task_id, "context": metadata.get("context", {})}
