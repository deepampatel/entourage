"""Security enforcer — validates write paths, network access, and bash commands.

Learn: The enforcer runs in two modes:
  - strict: violations are blocked AND logged
  - permissive: violations are logged only (for gradual rollout)

Write path enforcement prevents agents from escaping their worktree.
Network allowlist prevents unauthorized external access.
Bash command patterns catch dangerous operations (rm -rf .git, DROP TABLE, etc.).

All violations are persisted to the security_audit table for auditing.
"""

import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import SecurityAudit

logger = logging.getLogger("openclaw.services.security_enforcer")

# Built-in denied bash patterns
DENIED_BASH_PATTERNS = [
    r"rm\s+-rf\s+\.git",          # Destroying git history
    r"rm\s+-rf\s+/",              # Root delete
    r"DROP\s+TABLE",              # SQL injection via shell
    r"DROP\s+DATABASE",
    r"curl.*\|\s*sh",             # Piping curl to shell
    r"curl.*\|\s*bash",
    r"wget.*\|\s*sh",
    r"chmod\s+777",               # Over-permissive file perms
    r"eval\s*\(",                 # Eval injection
    r"\/etc\/shadow",             # Sensitive file access
    r"\/etc\/passwd",
]


@dataclass
class SecurityViolation:
    """Record of a security policy violation."""

    kind: str  # network|write_path|denied_bash
    agent_id: str
    team_id: str
    run_task_id: Optional[int]
    detail: str  # what was attempted
    rule: str  # which rule matched
    action: str  # blocked|logged


class SecurityEnforcer:
    """Validates agent actions against security policies.

    Learn: The enforcer is stateless per-call — it receives the DB session
    and mode from the caller. This makes it easy to test and inject.
    """

    def __init__(self, db: AsyncSession, mode: str = "strict"):
        self._db = db
        self._mode = mode  # strict|permissive

    async def validate_write_path(
        self,
        path: str,
        agent_id: str,
        team_id: str,
        task_id: Optional[int],
        allowed_paths: list[str],
    ) -> Optional[SecurityViolation]:
        """Block writes outside allowed paths (worktree + explicit dirs).

        Catches parent traversal (../../etc/passwd) attacks.
        """
        # Normalize the path
        normalized = os.path.normpath(os.path.abspath(path))

        # Check for parent traversal attempts
        if ".." in path:
            return SecurityViolation(
                kind="write_path",
                agent_id=agent_id,
                team_id=team_id,
                run_task_id=task_id,
                detail=f"Parent traversal in path: {path}",
                rule="no_parent_traversal",
                action="blocked" if self._mode == "strict" else "logged",
            )

        # Check if path is within any allowed path
        for allowed in allowed_paths:
            allowed_norm = os.path.normpath(os.path.abspath(allowed))
            if normalized.startswith(allowed_norm):
                return None  # Allowed

        return SecurityViolation(
            kind="write_path",
            agent_id=agent_id,
            team_id=team_id,
            run_task_id=task_id,
            detail=f"Write outside allowed paths: {path}",
            rule=f"allowed_paths:{','.join(allowed_paths)}",
            action="blocked" if self._mode == "strict" else "logged",
        )

    async def validate_network_access(
        self,
        domain: str,
        agent_id: str,
        team_id: str,
        task_id: Optional[int],
        allowlist: list[str],
    ) -> Optional[SecurityViolation]:
        """Check domain against network allowlist.

        Supports exact match and wildcard (*.github.com).
        """
        for pattern in allowlist:
            if fnmatch.fnmatch(domain.lower(), pattern.lower()):
                return None  # Allowed

        return SecurityViolation(
            kind="network",
            agent_id=agent_id,
            team_id=team_id,
            run_task_id=task_id,
            detail=f"Network access to unauthorized domain: {domain}",
            rule=f"not_in_allowlist",
            action="blocked" if self._mode == "strict" else "logged",
        )

    async def validate_bash_command(
        self,
        command: str,
        agent_id: str,
        team_id: str,
        task_id: Optional[int],
        extra_patterns: list[str] | None = None,
    ) -> Optional[SecurityViolation]:
        """Check command against denied bash patterns."""
        all_patterns = DENIED_BASH_PATTERNS + (extra_patterns or [])

        for pattern in all_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return SecurityViolation(
                    kind="denied_bash",
                    agent_id=agent_id,
                    team_id=team_id,
                    run_task_id=task_id,
                    detail=f"Denied bash command: {command[:200]}",
                    rule=pattern,
                    action="blocked" if self._mode == "strict" else "logged",
                )

        return None

    async def record_violation(self, violation: SecurityViolation) -> None:
        """Persist violation to security_audit table."""
        audit = SecurityAudit(
            kind=violation.kind,
            agent_id=violation.agent_id,
            team_id=violation.team_id,
            run_task_id=violation.run_task_id,
            detail=violation.detail,
            rule=violation.rule,
            action=violation.action,
        )
        self._db.add(audit)
        await self._db.commit()

        logger.warning(
            "Security violation: %s (agent=%s, action=%s)",
            violation.detail[:100],
            violation.agent_id,
            violation.action,
        )

    async def get_violations(
        self,
        team_id: str,
        agent_id: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> list[SecurityAudit]:
        """Query audit log."""
        q = (
            select(SecurityAudit)
            .where(SecurityAudit.team_id == team_id)
            .order_by(SecurityAudit.created_at.desc())
            .limit(limit)
        )
        if agent_id:
            q = q.where(SecurityAudit.agent_id == agent_id)
        if kind:
            q = q.where(SecurityAudit.kind == kind)

        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def get_summary(self, team_id: str, days: int = 7) -> dict:
        """Aggregate violation counts by kind and agent."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Total count
        q_total = (
            select(func.count())
            .select_from(SecurityAudit)
            .where(
                SecurityAudit.team_id == team_id,
                SecurityAudit.created_at >= since,
            )
        )
        result = await self._db.execute(q_total)
        total = result.scalar() or 0

        # Count by kind
        q_by_kind = (
            select(SecurityAudit.kind, func.count())
            .where(
                SecurityAudit.team_id == team_id,
                SecurityAudit.created_at >= since,
            )
            .group_by(SecurityAudit.kind)
        )
        result = await self._db.execute(q_by_kind)
        by_kind = {row[0]: row[1] for row in result.all()}

        # Count by agent
        q_by_agent = (
            select(SecurityAudit.agent_id, func.count())
            .where(
                SecurityAudit.team_id == team_id,
                SecurityAudit.created_at >= since,
            )
            .group_by(SecurityAudit.agent_id)
        )
        result = await self._db.execute(q_by_agent)
        by_agent = {str(row[0]): row[1] for row in result.all()}

        return {
            "total_violations": total,
            "by_kind": by_kind,
            "by_agent": by_agent,
            "period_days": days,
        }
