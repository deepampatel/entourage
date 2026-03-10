"""Pydantic schemas for Sandbox API requests and responses."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SandboxRunCreate(BaseModel):
    test_cmd: str = Field(..., min_length=1)
    image: str = Field(default="python:3.12-slim", max_length=200)
    setup_cmd: Optional[str] = None
    timeout: int = Field(default=300, ge=10, le=1800)


class SandboxRunRead(BaseModel):
    id: int
    sandbox_id: str
    run_id: Optional[uuid.UUID] = None
    run_task_id: Optional[int] = None
    team_id: uuid.UUID
    test_cmd: str
    exit_code: Optional[int] = None
    passed: bool
    stdout: str
    stderr: str
    duration_seconds: float
    image: str
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
