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


@router.get("/repos/scan")
async def scan_for_repos(
    db: AsyncSession = Depends(get_db),
):
    """Scan common directories for git repos. Returns list of discovered repos."""
    import os
    import asyncio

    home = os.path.expanduser("~")
    scan_dirs = [
        os.path.join(home, "Documents", "GitHub"),
        os.path.join(home, "projects"),
        os.path.join(home, "code"),
        os.path.join(home, "repos"),
        os.path.join(home, "dev"),
        os.path.join(home, "src"),
        os.path.join(home, "workspace"),
        os.path.join(home, "Desktop"),
    ]

    found = []
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        try:
            for entry in os.scandir(scan_dir):
                if entry.is_dir() and os.path.isdir(os.path.join(entry.path, ".git")):
                    # It's a git repo
                    from openclaw.services.git_service import GitService
                    git_svc = GitService(db)
                    info = await git_svc.validate_repo(entry.path)
                    if info["valid"]:
                        found.append({
                            "name": entry.name,
                            "path": entry.path,
                            "default_branch": info["default_branch"],
                            "remote_url": info["remote_url"],
                            "is_dirty": info["is_dirty"],
                        })
        except PermissionError:
            continue

    return found


@router.post("/repos/validate")
async def validate_repo_path(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Validate a path is a git repo and return health info."""
    from openclaw.services.git_service import GitService

    local_path = body.get("local_path", "")
    if not local_path:
        raise HTTPException(status_code=400, detail="local_path required")

    git_svc = GitService(db)
    return await git_svc.validate_repo(local_path)


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
