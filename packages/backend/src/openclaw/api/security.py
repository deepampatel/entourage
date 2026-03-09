"""Security API — violation audit log and network allowlist management.

Learn: Exposes the SecurityEnforcer's audit trail and allows teams to
manage their network allowlist via the API. All endpoints are protected
by the standard auth dependency (applied at include_router level).
"""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.engine import get_db
from openclaw.services.security_enforcer import SecurityEnforcer
from openclaw.schemas.security import (
    NetworkAllowlistUpdate,
    SecuritySummary,
    SecurityViolationRead,
)

router = APIRouter()


@router.get(
    "/teams/{team_id}/security/violations",
    response_model=list[SecurityViolationRead],
)
async def list_violations(
    team_id: str,
    kind: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """List security violations for a team, optionally filtered by kind."""
    enforcer = SecurityEnforcer(db)
    return await enforcer.get_violations(
        team_id=team_id, kind=kind, limit=limit
    )


@router.get(
    "/teams/{team_id}/security/summary",
    response_model=SecuritySummary,
)
async def get_security_summary(
    team_id: str,
    days: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated security violation summary for a team."""
    enforcer = SecurityEnforcer(db)
    return await enforcer.get_summary(team_id=team_id, days=days)


@router.get(
    "/teams/{team_id}/security/network-allowlist",
    response_model=list[str],
)
async def get_network_allowlist(
    team_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the network allowlist for a team from team config."""
    from openclaw.db.models import Team

    team = await db.get(Team, team_id)
    if not team:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Team not found")
    config = team.config or {}
    return config.get("network_allowlist", [])


@router.post(
    "/teams/{team_id}/security/network-allowlist",
    response_model=list[str],
)
async def add_network_allowlist(
    team_id: str,
    body: NetworkAllowlistUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Add a domain to the team's network allowlist."""
    from openclaw.db.models import Team

    team = await db.get(Team, team_id)
    if not team:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Team not found")

    config = dict(team.config) if team.config else {}
    allowlist = list(config.get("network_allowlist", []))
    if body.domain not in allowlist:
        allowlist.append(body.domain)
    config["network_allowlist"] = allowlist
    team.config = config
    await db.commit()
    return allowlist


@router.delete(
    "/teams/{team_id}/security/network-allowlist/{domain}",
    response_model=list[str],
)
async def remove_network_allowlist(
    team_id: str,
    domain: str,
    db: AsyncSession = Depends(get_db),
):
    """Remove a domain from the team's network allowlist."""
    from openclaw.db.models import Team

    team = await db.get(Team, team_id)
    if not team:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Team not found")

    config = dict(team.config) if team.config else {}
    allowlist = list(config.get("network_allowlist", []))
    if domain in allowlist:
        allowlist.remove(domain)
    config["network_allowlist"] = allowlist
    team.config = config
    await db.commit()
    return allowlist
