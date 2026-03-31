"""Review comment deduplication — prevents re-sending identical review feedback.

Uses SHA-256 fingerprinting of comment content to track which comments have
already been dispatched to an agent. Prevents the same feedback from being
sent multiple times across review cycles.

Inspired by ComposioHQ/agent-orchestrator's review comment fingerprinting.
"""

import hashlib
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import ReviewComment

logger = logging.getLogger("openclaw.services.review_dedup")


class ReviewDeduplicator:
    """Track and deduplicate review comments sent to agents."""

    def __init__(self, db: AsyncSession):
        self._db = db
        # In-memory cache of fingerprints already dispatched per task
        # Key: task_id, Value: set of fingerprints
        self._dispatched: dict[int, set[str]] = {}

    @staticmethod
    def fingerprint(comment: ReviewComment) -> str:
        """Create a SHA-256 fingerprint for a review comment.

        The fingerprint captures the semantic content (file, line, text)
        so that reformatted but identical feedback is still deduplicated.
        """
        parts = [
            comment.file_path or "",
            str(comment.line_number or 0),
            comment.content.strip().lower(),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def filter_new_comments(
        self,
        task_id: int,
        comments: list[ReviewComment],
    ) -> list[ReviewComment]:
        """Filter out comments that have already been dispatched for this task.

        Returns only comments whose fingerprint hasn't been seen before.
        """
        if task_id not in self._dispatched:
            # Load previously dispatched fingerprints from all reviews for this task
            self._dispatched[task_id] = await self._load_dispatched(task_id)

        seen = self._dispatched[task_id]
        new_comments = []

        for comment in comments:
            fp = self.fingerprint(comment)
            if fp not in seen:
                new_comments.append(comment)
                seen.add(fp)
            else:
                logger.debug(
                    "Dedup: skipping comment %d (fp=%s, task=%d)",
                    comment.id, fp, task_id,
                )

        if len(comments) != len(new_comments):
            logger.info(
                "Dedup: filtered %d/%d comments for task %d",
                len(comments) - len(new_comments),
                len(comments),
                task_id,
            )

        return new_comments

    async def _load_dispatched(self, task_id: int) -> set[str]:
        """Load fingerprints of all existing comments for a task's reviews."""
        from openclaw.db.models import Review

        result = await self._db.execute(
            select(ReviewComment)
            .join(Review, ReviewComment.review_id == Review.id)
            .where(Review.task_id == task_id)
        )
        comments = list(result.scalars().all())
        return {self.fingerprint(c) for c in comments}

    def mark_dispatched(self, task_id: int, comments: list[ReviewComment]):
        """Mark comments as dispatched (after sending to agent)."""
        if task_id not in self._dispatched:
            self._dispatched[task_id] = set()
        for comment in comments:
            self._dispatched[task_id].add(self.fingerprint(comment))

    def clear_cache(self, task_id: Optional[int] = None):
        """Clear the in-memory dedup cache."""
        if task_id:
            self._dispatched.pop(task_id, None)
        else:
            self._dispatched.clear()
