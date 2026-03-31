"""Sibling context carryover — parallel task awareness.

When RunTasks execute in parallel, each agent needs awareness of what its
sibling tasks are doing to avoid duplicating work or creating conflicts.

This service builds a "sibling context" section that gets injected into
the agent's prompt, containing:
- What other tasks are running in parallel
- Their descriptions and assigned agents
- Any contracts/interfaces they share
- Completed sibling results (for later tasks in the DAG)

Inspired by ComposioHQ/agent-orchestrator's lineage + sibling awareness.
"""

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import Contract, Run, RunTask

logger = logging.getLogger("openclaw.services.sibling_context")


class SiblingContextBuilder:
    """Build sibling awareness context for parallel task execution."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def build_context(
        self,
        run_id,
        current_task_id: int,
    ) -> str:
        """Build sibling context section for a task's prompt.

        Returns a formatted string to inject into the agent prompt,
        or empty string if no siblings exist.
        """
        # Load all tasks in this run
        result = await self._db.execute(
            select(RunTask)
            .where(RunTask.run_id == run_id)
            .order_by(RunTask.id)
        )
        all_tasks = list(result.scalars().all())

        if len(all_tasks) <= 1:
            return ""

        current = None
        for t in all_tasks:
            if t.id == current_task_id:
                current = t
                break

        if not current:
            return ""

        # Find siblings: tasks at the same dependency level (no dependency on current)
        current_deps = set(current.dependencies or [])
        current_idx = next(
            (i for i, t in enumerate(all_tasks) if t.id == current_task_id),
            -1,
        )

        parallel_siblings = []
        completed_predecessors = []
        dependent_successors = []

        for i, task in enumerate(all_tasks):
            if task.id == current_task_id:
                continue

            task_deps = set(task.dependencies or [])

            if current_idx in task_deps:
                # This task depends on current → it's a successor
                dependent_successors.append(task)
            elif task.status == "done":
                # Completed task → predecessor context
                completed_predecessors.append(task)
            elif task.status in ("in_progress", "todo"):
                # Check if they share the same dependency level (parallel)
                if task_deps == current_deps or (
                    not task_deps and not current_deps
                ):
                    parallel_siblings.append(task)
                elif i not in current_deps and current_idx not in task_deps:
                    # Not in each other's dependency chain → parallel
                    parallel_siblings.append(task)

        # Build context sections
        sections = []

        if parallel_siblings:
            sections.append("PARALLEL TASKS (running alongside you):")
            sections.append(
                "These tasks are being worked on simultaneously. "
                "Do NOT duplicate their work. Coordinate via shared interfaces."
            )
            for sib in parallel_siblings:
                status = f" [{sib.status}]" if sib.status != "todo" else ""
                sections.append(f"  - Task #{sib.id}: {sib.title}{status}")
                if sib.description:
                    # First 200 chars of description
                    desc = sib.description[:200]
                    if len(sib.description) > 200:
                        desc += "..."
                    sections.append(f"    {desc}")
            sections.append("")

        if completed_predecessors:
            sections.append("COMPLETED PREDECESSOR TASKS:")
            sections.append(
                "These tasks finished before you. Build on their work."
            )
            for pred in completed_predecessors:
                sections.append(f"  - Task #{pred.id}: {pred.title} [done]")
                # Include result summary if available
                if pred.result and isinstance(pred.result, dict):
                    stdout = pred.result.get("stdout", "")
                    if stdout:
                        summary = stdout[:300]
                        if len(stdout) > 300:
                            summary += "..."
                        sections.append(f"    Result: {summary}")
            sections.append("")

        if dependent_successors:
            sections.append("TASKS WAITING ON YOU:")
            sections.append(
                "These tasks will start after you finish. "
                "Ensure your work is complete and interfaces are clean."
            )
            for succ in dependent_successors:
                sections.append(f"  - Task #{succ.id}: {succ.title}")
            sections.append("")

        # Load contracts if any
        contracts_context = await self._build_contracts_context(run_id, current_task_id)
        if contracts_context:
            sections.append(contracts_context)

        if not sections:
            return ""

        return "SIBLING CONTEXT:\n" + "\n".join(sections)

    async def _build_contracts_context(
        self, run_id, current_task_id: int
    ) -> str:
        """Build contract awareness section."""
        result = await self._db.execute(
            select(Contract).where(Contract.run_id == run_id)
        )
        contracts = list(result.scalars().all())

        if not contracts:
            return ""

        # Find contracts relevant to this task
        relevant = [
            c for c in contracts
            if c.run_task_id == current_task_id or c.run_task_id is None
        ]

        if not relevant:
            return ""

        lines = [
            "SHARED CONTRACTS (interfaces you must respect):",
            "These contracts define the interfaces between parallel tasks.",
            "You MUST implement your side of these contracts exactly as specified.",
        ]
        for contract in relevant:
            locked_info = ""
            if contract.locked:
                locked_info = f" [locked by agent {contract.locked_by}]"
            lines.append(
                f"  - {contract.contract_type.upper()}: {contract.name}{locked_info}"
            )
            spec = contract.specification
            if isinstance(spec, dict):
                # Show key parts of the spec
                for key, value in list(spec.items())[:5]:
                    lines.append(f"    {key}: {value}")

        return "\n".join(lines)
