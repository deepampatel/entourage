"""Team, Agent, and Repo API routes.

Learn: FastAPI routers define HTTP endpoints. Each route function
receives dependencies (db session) via Depends() and delegates
to the service layer. Routes handle HTTP concerns (status codes,
error responses), services handle business logic.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import get_db
from openclaw.schemas.team import (
    AgentCreate,
    AgentRead,
    AgentUpdate,
    OrgCreate,
    OrgRead,
    RepoCreate,
    RepoRead,
    TeamCreate,
    TeamDetail,
    TeamRead,
)
from openclaw.services.team_service import TeamService

router = APIRouter()


def _svc(db: AsyncSession = Depends(get_db)) -> TeamService:
    return TeamService(db)


# ─── Organizations ──────────────────────────────────────

@router.post("/orgs", response_model=OrgRead, status_code=201)
async def create_org(body: OrgCreate, svc: TeamService = Depends(_svc)):
    org = await svc.create_org(name=body.name, slug=body.slug)
    await svc.db.commit()
    return org


@router.get("/orgs", response_model=list[OrgRead])
async def list_orgs(svc: TeamService = Depends(_svc)):
    return await svc.list_orgs()


# ─── Teams ──────────────────────────────────────────────

@router.post("/orgs/{org_id}/teams", response_model=TeamRead, status_code=201)
async def create_team(
    org_id: uuid.UUID,
    body: TeamCreate,
    svc: TeamService = Depends(_svc),
):
    """Create a team. Auto-provisions a default manager agent."""
    team = await svc.create_team(org_id=org_id, name=body.name, slug=body.slug)
    return team


@router.get("/orgs/{org_id}/teams", response_model=list[TeamRead])
async def list_teams(org_id: uuid.UUID, svc: TeamService = Depends(_svc)):
    return await svc.list_teams(org_id)


@router.get("/teams/{team_id}", response_model=TeamDetail)
async def get_team(team_id: uuid.UUID, svc: TeamService = Depends(_svc)):
    team = await svc.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


# ─── Agents ─────────────────────────────────────────────

@router.post("/teams/{team_id}/agents", response_model=AgentRead, status_code=201)
async def create_agent(
    team_id: uuid.UUID,
    body: AgentCreate,
    svc: TeamService = Depends(_svc),
):
    agent = await svc.create_agent(
        team_id=team_id,
        name=body.name,
        role=body.role,
        model=body.model,
        config=body.config,
    )
    return agent


@router.get("/teams/{team_id}/agents", response_model=list[AgentRead])
async def list_agents(team_id: uuid.UUID, svc: TeamService = Depends(_svc)):
    return await svc.list_agents(team_id)


@router.patch("/agents/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update agent fields (name, role, model, config)."""
    from openclaw.db.models import Agent

    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if body.name is not None:
        agent.name = body.name
    if body.role is not None:
        agent.role = body.role
    if body.model is not None:
        agent.model = body.model
    if body.config is not None:
        agent.config = {**agent.config, **body.config}

    await db.commit()
    await db.refresh(agent)
    return agent


# ─── Repositories ───────────────────────────────────────

@router.post("/teams/{team_id}/repos", response_model=RepoRead, status_code=201)
async def register_repo(
    team_id: uuid.UUID,
    body: RepoCreate,
    svc: TeamService = Depends(_svc),
):
    repo = await svc.register_repo(
        team_id=team_id,
        name=body.name,
        local_path=body.local_path,
        default_branch=body.default_branch,
        config=body.config,
    )
    return repo


@router.get("/teams/{team_id}/repos", response_model=list[RepoRead])
async def list_repos(team_id: uuid.UUID, svc: TeamService = Depends(_svc)):
    return await svc.list_repos(team_id)
