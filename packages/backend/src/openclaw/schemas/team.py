"""Pydantic schemas for teams, orgs, agents, and repos.

Learn: Pydantic v2 models validate request/response data. Separate
"Create" schemas (input) from "Read" schemas (output) for clean APIs.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ─── Organizations ──────────────────────────────────────

class OrgCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class OrgRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Teams ──────────────────────────────────────────────

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class TeamRead(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamDetail(TeamRead):
    """Team with nested agents and repos."""
    agents: list["AgentRead"] = []
    repositories: list["RepoRead"] = []


# ─── Agents ─────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(default="engineer", pattern=r"^(manager|engineer|reviewer)$")
    model: str = Field(default="claude-sonnet-4-20250514")
    config: dict = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[str] = Field(None, pattern=r"^(manager|engineer|reviewer)$")
    model: Optional[str] = None
    config: Optional[dict] = None


class AgentRead(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    role: str
    model: str
    config: dict
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Repositories ───────────────────────────────────────

class RepoCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    local_path: str = Field(..., min_length=1)
    default_branch: str = Field(default="main")
    config: dict = Field(default_factory=dict)


class RepoRead(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    local_path: str
    default_branch: str
    config: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# Rebuild forward refs for nested models
TeamDetail.model_rebuild()
