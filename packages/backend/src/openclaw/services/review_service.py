"""Code review + merge service.

Learn: Manages the review lifecycle:
1. request_review → creates a Review row (attempt N)
2. add_comment → reviewer leaves inline comments
3. submit_verdict → approve / request_changes / reject
4. On approve → creates a MergeJob and queues it

The actual merge is handled by a separate worker (future).
This service manages the DB records and event trail.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openclaw.db.models import Agent, MergeJob, Review, ReviewComment, Task
from openclaw.events.store import EventStore
from openclaw.events.types import (
    MERGE_QUEUED,
    REVIEW_COMMENT_ADDED,
    REVIEW_CREATED,
    REVIEW_FEEDBACK_SENT,
    REVIEW_VERDICT,
)

logger = structlog.get_logger()


class ReviewNotFoundError(Exception):
    """Raised when a review is not found."""


class ReviewAlreadyResolvedError(Exception):
    """Raised when trying to verdict an already-resolved review."""


class TaskNotFoundError(Exception):
    """Raised when a task is not found."""


class ReviewService:
    """Manages code reviews, comments, and merge jobs."""

    def __init__(self, db: AsyncSession, events: EventStore):
        self.db = db
        self.events = events

    # ─── Create review ────────────────────────────────────

    async def request_review(
        self,
        task_id: int,
        *,
        reviewer_id: Optional[str] = None,
        reviewer_type: str = "user",
    ) -> Review:
        """Create a new review for a task.

        Learn: Auto-increments the attempt number. Each new review
        request is a fresh review cycle. If no reviewer is specified,
        checks for an idle reviewer agent in the team and auto-assigns.
        If reviewer is an agent, sends them a message to trigger dispatch.
        Also attempts to push the branch and create a PR.
        """
        task = await self.db.get(Task, task_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found")

        # ── Auto-assign to reviewer agent if none specified ────
        if not reviewer_id:
            reviewer_agent = await self._find_reviewer_agent(task.team_id)
            if reviewer_agent:
                reviewer_id = str(reviewer_agent.id)
                reviewer_type = "agent"

        # Get current attempt number
        q = (
            select(func.coalesce(func.max(Review.attempt), 0))
            .where(Review.task_id == task_id)
        )
        result = await self.db.execute(q)
        current_max = result.scalar()
        next_attempt = current_max + 1

        review = Review(
            task_id=task_id,
            attempt=next_attempt,
            reviewer_id=uuid.UUID(reviewer_id) if reviewer_id else None,
            reviewer_type=reviewer_type,
        )
        self.db.add(review)
        await self.db.flush()

        await self.events.append(
            stream_id=f"task:{task_id}",
            event_type=REVIEW_CREATED,
            data={
                "review_id": review.id,
                "task_id": task_id,
                "attempt": next_attempt,
                "reviewer_id": reviewer_id,
                "reviewer_type": reviewer_type,
            },
        )

        await self.db.commit()

        # ── Auto-push branch and create PR (best-effort) ──────
        await self._auto_push_and_create_pr(task)

        # ── Dispatch reviewer agent if assigned ────────────────
        if reviewer_type == "agent" and reviewer_id:
            await self._dispatch_reviewer_agent(task, review, reviewer_id)

        # Re-fetch with eagerly loaded comments (async can't lazy-load)
        return await self.get_review(review.id)

    # ─── Add comment ──────────────────────────────────────

    async def add_comment(
        self,
        review_id: int,
        *,
        author_id: str,
        author_type: str = "user",
        content: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
    ) -> ReviewComment:
        """Add a comment to a review."""
        review = await self.db.get(Review, review_id)
        if not review:
            raise ReviewNotFoundError(f"Review {review_id} not found")

        comment = ReviewComment(
            review_id=review_id,
            author_id=uuid.UUID(author_id),
            author_type=author_type,
            file_path=file_path,
            line_number=line_number,
            content=content,
        )
        self.db.add(comment)
        await self.db.flush()

        await self.events.append(
            stream_id=f"task:{review.task_id}",
            event_type=REVIEW_COMMENT_ADDED,
            data={
                "review_id": review_id,
                "comment_id": comment.id,
                "file_path": file_path,
                "line_number": line_number,
            },
        )

        await self.db.commit()
        await self.db.refresh(comment)
        return comment

    # ─── Submit verdict ───────────────────────────────────

    async def submit_verdict(
        self,
        review_id: int,
        *,
        verdict: str,
        summary: Optional[str] = None,
        reviewer_id: Optional[str] = None,
        reviewer_type: str = "user",
    ) -> Review:
        """Submit a verdict on a review (approve, request_changes, reject).

        Learn: On 'approve', this also enqueues a merge job for each
        repo associated with the task.
        """
        if verdict not in ("approve", "request_changes", "reject"):
            raise ValueError(f"Invalid verdict: {verdict}")

        review = await self.db.get(
            Review, review_id, options=[selectinload(Review.comments)]
        )
        if not review:
            raise ReviewNotFoundError(f"Review {review_id} not found")

        if review.verdict is not None:
            raise ReviewAlreadyResolvedError(
                f"Review {review_id} already has verdict: {review.verdict}"
            )

        review.verdict = verdict
        review.summary = summary
        review.resolved_at = datetime.now(timezone.utc)
        if reviewer_id:
            review.reviewer_id = uuid.UUID(reviewer_id)
            review.reviewer_type = reviewer_type

        await self.events.append(
            stream_id=f"task:{review.task_id}",
            event_type=REVIEW_VERDICT,
            data={
                "review_id": review_id,
                "task_id": review.task_id,
                "verdict": verdict,
                "summary": summary,
                "reviewer_id": reviewer_id,
            },
        )

        await self.db.commit()

        # ── Handle request_changes: send feedback + re-dispatch ──
        if verdict == "request_changes":
            await self._handle_request_changes(review, summary)

        # ── Handle agent approve: keep in in_review for human ──
        # Agent approval is a first-pass check. The task stays in
        # in_review so a human can do the final review. We don't
        # auto-transition to in_approval.
        if verdict == "approve" and reviewer_type == "agent":
            logger.info(
                "review.agent_approved",
                task_id=review.task_id,
                review_id=review_id,
                msg="Agent approved — awaiting human review",
            )

        # Re-fetch with eagerly loaded comments
        return await self.get_review(review.id)

    # ─── Handle request_changes ────────────────────────────

    async def _handle_request_changes(
        self,
        review: Review,
        summary: Optional[str] = None,
    ) -> None:
        """Close the feedback loop: send review comments to agent and re-dispatch.

        Learn: This is what makes the review cycle autonomous. When a reviewer
        gives "request_changes":
        1. Collect all review comments into a formatted feedback message
        2. Transition the task back to in_progress
        3. Send the feedback as a message to the assignee agent
        4. The message INSERT triggers PG NOTIFY → dispatcher → agent re-runs

        The agent's prompt tells it to check its inbox first, so it will
        read the feedback and address each comment.
        """
        from openclaw.services.task_service import MessageService, TaskService

        task = await self.db.get(Task, review.task_id)
        if not task or not task.assignee_id:
            return  # No assignee to notify

        # ── Format feedback from review comments (deduplicated) ──
        comments = review.comments or []

        # Filter out comments already dispatched in previous review cycles
        try:
            from openclaw.services.review_dedup import ReviewDeduplicator
            dedup = ReviewDeduplicator(self.db)
            comments = await dedup.filter_new_comments(review.task_id, comments)
            dedup.mark_dispatched(review.task_id, comments)
        except Exception:
            pass  # Dedup is best-effort; fall through to send all comments

        feedback_lines = [f"## Review Feedback (Attempt #{review.attempt})"]
        if summary:
            feedback_lines.append(f"\n**Summary:** {summary}\n")
        if comments:
            feedback_lines.append("**Comments to address:**")
            for c in comments:
                loc = f"{c.file_path}:{c.line_number}" if c.file_path else "General"
                feedback_lines.append(f"- **{loc}**: {c.content}")
        feedback_text = "\n".join(feedback_lines)

        # ── Transition task back to in_progress ───────────────
        task_svc = TaskService(self.db)
        await task_svc.change_status(review.task_id, "in_progress")

        # ── Send feedback message to the assignee agent ───────
        msg_svc = MessageService(self.db)
        await msg_svc.send_message(
            team_id=task.team_id,
            sender_id=review.reviewer_id or task.team_id,
            sender_type=review.reviewer_type or "user",
            recipient_id=task.assignee_id,
            recipient_type="agent",
            content=feedback_text,
            task_id=review.task_id,
        )

        # ── Record feedback event ─────────────────────────────
        await self.events.append(
            stream_id=f"task:{review.task_id}",
            event_type=REVIEW_FEEDBACK_SENT,
            data={
                "review_id": review.id,
                "task_id": review.task_id,
                "assignee_id": str(task.assignee_id),
                "comment_count": len(comments),
            },
        )
        await self.db.commit()

    # ─── Auto-assign reviewer agent ──────────────────────

    async def _find_reviewer_agent(self, team_id) -> Optional[Agent]:
        """Find an idle reviewer agent in the team.

        Learn: If a team has agents with role='reviewer', they get
        first-pass review before human review. This enables AI-powered
        code review that catches bugs automatically.
        """
        q = (
            select(Agent)
            .where(
                Agent.team_id == team_id,
                Agent.role == "reviewer",
                Agent.status == "idle",
            )
            .limit(1)
        )
        result = await self.db.execute(q)
        return result.scalars().first()

    # ─── Dispatch reviewer agent ──────────────────────────

    async def _dispatch_reviewer_agent(
        self, task: Task, review: Review, reviewer_id: str
    ) -> None:
        """Send a message to the reviewer agent to trigger dispatch.

        Learn: The message triggers PG NOTIFY → dispatcher → reviewer
        agent runs with review context. The reviewer prompt tells
        the agent to read the diff and leave comments.
        """
        from openclaw.services.task_service import MessageService

        msg_svc = MessageService(self.db)
        review_msg = (
            f"## Code Review Request\n\n"
            f"Task #{task.id}: {task.title}\n\n"
            f"Review ID: {review.id}\n"
            f"Attempt: {review.attempt}\n\n"
            f"Please review the code changes and provide feedback."
        )
        await msg_svc.send_message(
            team_id=task.team_id,
            sender_id=task.assignee_id or task.team_id,
            sender_type="agent",
            recipient_id=uuid.UUID(reviewer_id),
            recipient_type="agent",
            content=review_msg,
            task_id=task.id,
        )

    # ─── Auto-push and create PR ──────────────────────────

    async def _auto_push_and_create_pr(self, task: Task) -> None:
        """Best-effort: push branch and create a GitHub PR.

        Learn: This is fire-and-forget. If push fails (no remote, no
        git config), or PR creation fails (gh not installed, not authed),
        we log a warning and continue. The review flow should never break
        because of PR creation failure.
        """
        if not task.repo_ids:
            return

        try:
            from openclaw.services.git_service import GitService
            from openclaw.services.pr_service import PRService

            repo_id = task.repo_ids[0]
            git_svc = GitService(self.db)
            pr_svc = PRService(self.db, events=self.events)

            # Push the branch
            push_result = await git_svc.push_branch(task.id, repo_id)
            if not push_result.ok:
                logger.warning(
                    "auto_pr.push_failed",
                    task_id=task.id,
                    error=push_result.stderr,
                )
                return

            # Create the PR
            pr_result = await pr_svc.create_pr(task.id, repo_id)
            if "error" in pr_result:
                logger.warning(
                    "auto_pr.create_failed",
                    task_id=task.id,
                    error=pr_result["error"],
                )
        except Exception as e:
            logger.warning("auto_pr.error", task_id=task.id, error=str(e))

    # ─── Get review ───────────────────────────────────────

    async def get_review(self, review_id: int) -> Optional[Review]:
        """Get a review by ID with its comments.

        Learn: We use a SELECT query instead of db.get() because db.get()
        can return a cached instance from the identity map without re-running
        selectinload. A fresh query ensures comments are always loaded.
        """
        q = (
            select(Review)
            .where(Review.id == review_id)
            .options(selectinload(Review.comments))
        )
        result = await self.db.execute(q)
        return result.scalars().first()

    # ─── List reviews for task ────────────────────────────

    async def list_reviews(self, task_id: int) -> list[Review]:
        """Get all reviews for a task."""
        q = (
            select(Review)
            .where(Review.task_id == task_id)
            .options(selectinload(Review.comments))
            .order_by(Review.attempt.desc())
        )
        result = await self.db.execute(q)
        return list(result.scalars().all())

    # ─── Get latest review ────────────────────────────────

    async def get_latest_review(self, task_id: int) -> Optional[Review]:
        """Get the most recent review for a task."""
        q = (
            select(Review)
            .where(Review.task_id == task_id)
            .options(selectinload(Review.comments))
            .order_by(Review.attempt.desc())
            .limit(1)
        )
        result = await self.db.execute(q)
        return result.scalars().first()

    # ─── Merge job ────────────────────────────────────────

    async def create_merge_job(
        self,
        task_id: int,
        repo_id: str,
        strategy: str = "rebase",
    ) -> MergeJob:
        """Create a merge job for a task+repo.

        Learn: In production, this would also push the job to a Redis
        queue for the merge worker to pick up. For now, we just create
        the DB row.
        """
        task = await self.db.get(Task, task_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found")

        job = MergeJob(
            task_id=task_id,
            repo_id=uuid.UUID(repo_id),
            status="queued",
            strategy=strategy,
        )
        self.db.add(job)
        await self.db.flush()

        await self.events.append(
            stream_id=f"task:{task_id}",
            event_type=MERGE_QUEUED,
            data={
                "merge_job_id": job.id,
                "task_id": task_id,
                "repo_id": repo_id,
                "strategy": strategy,
            },
        )

        await self.db.commit()
        await self.db.refresh(job)
        return job

    # ─── Get merge status ─────────────────────────────────

    async def get_merge_status(self, task_id: int) -> dict:
        """Get the merge status for a task.

        Returns: latest review verdict, review attempt, merge jobs, can_merge flag.
        """
        latest = await self.get_latest_review(task_id)

        # Get merge jobs
        q = (
            select(MergeJob)
            .where(MergeJob.task_id == task_id)
            .order_by(MergeJob.created_at.desc())
        )
        result = await self.db.execute(q)
        merge_jobs = list(result.scalars().all())

        return {
            "task_id": task_id,
            "review_verdict": latest.verdict if latest else None,
            "review_attempt": latest.attempt if latest else 0,
            "merge_jobs": merge_jobs,
            "can_merge": latest is not None and latest.verdict == "approve",
        }
