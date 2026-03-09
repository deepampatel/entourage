"""Agent memory manager — persistent reflections and feedback across tasks.

Each agent accumulates learning over its pipeline lifetime via two files
stored in the worktree (or a fallback directory):
  - .openclaw/reflections.md  — self-written after each task completion
  - .openclaw/feedback.md     — reviewer/human feedback on the agent's work

The memory is injected into the agent's prompt before each task dispatch,
giving it a running "memory" of what worked, what failed, and what to watch for.

Learn: File-based memory is simple, portable, and git-friendly. It persists
across sessions and can be inspected by humans. The memory files live inside
the worktree so they're scoped to the pipeline's branch.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw.services.agent_memory")

OPENCLAW_DIR = ".openclaw"
REFLECTIONS_FILE = "reflections.md"
FEEDBACK_FILE = "feedback.md"


class AgentMemoryManager:
    """Manage persistent agent reflections and feedback."""

    async def write_reflection(
        self,
        agent_id: str,
        pipeline_task_id: int,
        reflection: str,
        worktree_path: str,
    ) -> str:
        """Append a reflection entry to .openclaw/reflections.md.

        Returns the path to the reflections file.
        """
        memory_dir = Path(worktree_path) / OPENCLAW_DIR
        memory_dir.mkdir(parents=True, exist_ok=True)

        filepath = memory_dir / REFLECTIONS_FILE
        timestamp = datetime.now(timezone.utc).isoformat()

        entry = (
            f"\n## Task #{pipeline_task_id} — {timestamp}\n"
            f"Agent: {agent_id}\n\n"
            f"{reflection}\n\n---\n"
        )

        with open(filepath, "a") as f:
            f.write(entry)

        logger.info(
            "Wrote reflection for agent %s, task %d",
            agent_id,
            pipeline_task_id,
        )
        return str(filepath)

    async def write_feedback(
        self,
        agent_id: str,
        pipeline_task_id: int,
        feedback: str,
        worktree_path: str,
    ) -> str:
        """Write reviewer/human feedback to .openclaw/feedback.md.

        Returns the path to the feedback file.
        """
        memory_dir = Path(worktree_path) / OPENCLAW_DIR
        memory_dir.mkdir(parents=True, exist_ok=True)

        filepath = memory_dir / FEEDBACK_FILE
        timestamp = datetime.now(timezone.utc).isoformat()

        entry = (
            f"\n## Feedback for Task #{pipeline_task_id} — {timestamp}\n"
            f"Agent: {agent_id}\n\n"
            f"{feedback}\n\n---\n"
        )

        with open(filepath, "a") as f:
            f.write(entry)

        logger.info(
            "Wrote feedback for agent %s, task %d",
            agent_id,
            pipeline_task_id,
        )
        return str(filepath)

    async def get_memory_context(
        self, agent_id: str, worktree_path: str
    ) -> dict[str, str]:
        """Read reflections.md and feedback.md as a dict.

        Returns {"reflections": "...", "feedback": "..."}.
        Either value may be empty string if the file doesn't exist.
        """
        memory_dir = Path(worktree_path) / OPENCLAW_DIR

        result: dict[str, str] = {}

        reflections_path = memory_dir / REFLECTIONS_FILE
        if reflections_path.exists():
            result["reflections"] = reflections_path.read_text()
        else:
            result["reflections"] = ""

        feedback_path = memory_dir / FEEDBACK_FILE
        if feedback_path.exists():
            result["feedback"] = feedback_path.read_text()
        else:
            result["feedback"] = ""

        return result

    async def inject_memory_into_prompt(
        self,
        base_prompt: str,
        agent_id: str,
        worktree_path: str,
    ) -> str:
        """Append memory files content to the agent's prompt.

        If no memory exists, returns the base prompt unchanged.
        """
        memory = await self.get_memory_context(agent_id, worktree_path)

        sections: list[str] = [base_prompt]

        if memory["reflections"]:
            sections.append(
                "\n\n## Your Previous Reflections\n\n"
                "Review these notes from your earlier tasks for context:\n\n"
                f"{memory['reflections']}"
            )

        if memory["feedback"]:
            sections.append(
                "\n\n## Feedback From Reviewers\n\n"
                "Address this feedback from reviewers and humans:\n\n"
                f"{memory['feedback']}"
            )

        return "".join(sections)
