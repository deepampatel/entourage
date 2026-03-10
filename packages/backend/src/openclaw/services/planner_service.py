"""Planner service — decomposes a human intent into a TaskGraph using Claude.

Uses the Anthropic API directly (tool_use for structured output), not the
Claude Code subprocess. This is a quick planning call, not a coding agent.
"""

import logging
import uuid
from typing import Optional

import anthropic

from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.config import settings
from openclaw.db.models import Run
from openclaw.events.store import EventStore
from openclaw.events.types import RUN_PLAN_GENERATED, RUN_STATUS_CHANGED
from openclaw.services.run_service import RunService

logger = logging.getLogger("openclaw.services.planner")


# ═══════════════════════════════════════════════════════════
# Run Templates
# ═══════════════════════════════════════════════════════════

RUN_TEMPLATES: dict[str, dict[str, object]] = {
    "feature": {
        "hints": (
            "Include DB migration if schema changes are needed, service layer, "
            "API endpoints, frontend components, and tests. Follow existing "
            "patterns in the codebase."
        ),
        "budget": 15.0,
    },
    "bugfix": {
        "hints": (
            "First reproduce the bug with a failing test, then fix the root cause, "
            "and add a regression test. Keep the fix minimal and focused."
        ),
        "budget": 5.0,
    },
    "refactor": {
        "hints": (
            "Keep behavior unchanged. Improve structure, reduce duplication, "
            "and update tests to match. Run existing tests to ensure no regressions."
        ),
        "budget": 10.0,
    },
    "migration": {
        "hints": (
            "Create migration script, update code references, add rollback plan, "
            "and test both upgrade and downgrade paths."
        ),
        "budget": 8.0,
    },
}


# ═══════════════════════════════════════════════════════════
# Task graph tool schema (for Claude's tool_use)
# ═══════════════════════════════════════════════════════════

TASK_GRAPH_TOOL = {
    "name": "create_task_graph",
    "description": (
        "Create a structured task graph that decomposes the given intent "
        "into concrete, independently executable coding tasks. Each task "
        "should be a discrete unit of work that an AI coding agent can "
        "complete in a single session."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Short title for the task (max 100 chars)",
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "Detailed description of what the agent should do, "
                                "including specific files to modify, patterns to follow, "
                                "and acceptance criteria."
                            ),
                        },
                        "complexity": {
                            "type": "string",
                            "enum": ["S", "M", "L", "XL"],
                            "description": (
                                "S: trivial fix/config (<30 min), "
                                "M: standard feature (30-90 min), "
                                "L: complex feature (90-180 min), "
                                "XL: major feature (180+ min)"
                            ),
                        },
                        "assigned_role": {
                            "type": "string",
                            "enum": ["engineer", "reviewer"],
                            "description": "Role of the agent that should execute this task",
                        },
                        "dependencies": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": (
                                "Zero-indexed IDs of tasks that must complete before this one. "
                                "Use [] for tasks with no dependencies."
                            ),
                        },
                        "integration_hints": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Hints about how this task's output integrates with other tasks. "
                                "E.g. 'Exports a function used by task 2', 'Adds a DB table "
                                "referenced in task 3'."
                            ),
                        },
                    },
                    "required": [
                        "title",
                        "description",
                        "complexity",
                        "assigned_role",
                        "dependencies",
                    ],
                },
            },
        },
        "required": ["tasks"],
    },
}


# ═══════════════════════════════════════════════════════════
# Cost estimation
# ═══════════════════════════════════════════════════════════

COMPLEXITY_COST_ESTIMATE: dict[str, float] = {
    "S": 0.10,
    "M": 0.50,
    "L": 2.00,
    "XL": 5.00,
}


# ═══════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════


class PlannerService:
    """Decomposes a human intent into a TaskGraph using Claude.

    When ANTHROPIC_API_KEY is set, calls Claude for intelligent decomposition.
    When empty, falls back to template-based task graphs so the platform
    is usable without an API key.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)
        self.run_svc = RunService(db)
        self._client = None  # Lazy init — only when Claude is actually needed

    @property
    def client(self):
        """Lazy-init Anthropic client — avoids crash when API key is empty."""
        if self._client is None:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY not set. Use template-based planning "
                    "or set the key to enable AI planning."
                )
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key
            )
        return self._client

    async def plan(self, run_id: uuid.UUID) -> dict:
        """Generate a TaskGraph for a run's intent.

        1. Load run (get intent)
        2. Transition run → planning
        3. Call Claude (or fallback to template) for TaskGraph
        4. Validate output
        5. Estimate cost per task
        6. Store task_graph in run, create RunTask rows
        7. Transition run → awaiting_plan_approval
        """
        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        # Transition to planning (if still in draft)
        if run.status == "draft":
            await self.run_svc.change_status(run_id, "planning")

        # Extract template from metadata (if set during creation)
        meta = run.run_metadata or {}
        template = meta.get("template")

        # Fallback to template-based planning when no API key
        if not settings.anthropic_api_key:
            logger.info(
                "No ANTHROPIC_API_KEY set, using template-based planning "
                "for run %s", run_id
            )
            return await self._plan_from_template(
                run_id, run.intent, template
            )

        # Build prompt and call Claude
        prompt = self._build_planning_prompt(
            run.intent, template=template
        )

        logger.info("Calling Claude to plan run %s", run_id)
        response = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            tools=[TASK_GRAPH_TOOL],
            tool_choice={"type": "tool", "name": "create_task_graph"},
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract task_graph from tool_use response
        task_graph = self._extract_task_graph(response)

        # Estimate costs
        estimated_cost = self._estimate_cost(task_graph)
        task_graph["estimated_cost_usd"] = estimated_cost

        # Store task graph + create RunTask rows
        await self.run_svc.set_task_graph(run_id, task_graph)

        # Update estimated cost on run
        run = await self.db.get(Run, run_id)
        run.estimated_cost_usd = estimated_cost
        await self.db.flush()

        # Record event
        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_PLAN_GENERATED,
            data={
                "run_id": str(run_id),
                "task_count": len(task_graph.get("tasks", [])),
                "estimated_cost_usd": estimated_cost,
            },
        )

        # Transition to awaiting approval
        await self.run_svc.change_status(
            run_id, "awaiting_plan_approval"
        )

        return task_graph

    def _build_planning_prompt(
        self,
        intent: str,
        conventions: Optional[list[dict]] = None,
        template: Optional[str] = None,
    ) -> str:
        """System prompt that instructs Claude to decompose intent into tasks."""
        parts = [
            "You are a senior software architect planning work for a team of "
            "AI coding agents. Decompose the following intent into a structured "
            "task graph.\n\n"
            "Guidelines:\n"
            "- Each task should be independently executable by a single agent\n"
            "- Tasks should be ordered by dependencies (earlier tasks first)\n"
            "- Use dependency IDs (0-indexed) to express ordering constraints\n"
            "- Keep tasks focused — one clear deliverable per task\n"
            "- Include integration hints so agents know how their work connects\n"
            "- Prefer smaller tasks (S/M) over large monolithic ones\n"
            "- Add a reviewer task for non-trivial changes\n"
            "- Description should include specific files, patterns, and acceptance criteria\n\n"
        ]

        # Inject template hints if a template is specified
        if template and template in RUN_TEMPLATES:
            tmpl = RUN_TEMPLATES[template]
            parts.append(
                f"Run template: {template}\n"
                f"Template guidelines: {tmpl['hints']}\n\n"
            )

        if conventions:
            parts.append("Team conventions to follow:\n")
            for c in conventions:
                parts.append(f"- {c.get('name', '')}: {c.get('content', '')}\n")
            parts.append("\n")

        parts.append(f"Intent:\n{intent}\n\n")
        parts.append(
            "Use the create_task_graph tool to output your plan. "
            "Ensure all dependencies are valid (reference only earlier task indices)."
        )

        return "".join(parts)

    def _extract_task_graph(self, response) -> dict:
        """Extract the task_graph dict from Claude's tool_use response."""
        for block in response.content:
            if block.type == "tool_use" and block.name == "create_task_graph":
                return block.input

        raise ValueError(
            "Claude did not return a create_task_graph tool call. "
            f"Response: {response.content}"
        )

    def _estimate_cost(self, task_graph: dict) -> float:
        """Rough cost estimate based on task complexity ratings."""
        total = 0.0
        for task in task_graph.get("tasks", []):
            complexity = task.get("complexity", "M")
            total += COMPLEXITY_COST_ESTIMATE.get(complexity, 0.50)
        return round(total, 2)

    # ── Template-based fallback ─────────────────────────────────

    TEMPLATE_TASK_GRAPHS: dict[str, list[dict]] = {
        "feature": [
            {
                "title": "Create data models",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [],
            },
            {
                "title": "Implement core logic",
                "complexity": "M",
                "assigned_role": "engineer",
                "dependencies": [0],
            },
            {
                "title": "Add API endpoints",
                "complexity": "M",
                "assigned_role": "engineer",
                "dependencies": [1],
            },
            {
                "title": "Write tests",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [2],
            },
        ],
        "bugfix": [
            {
                "title": "Reproduce and diagnose bug",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [],
            },
            {
                "title": "Implement fix",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [0],
            },
            {
                "title": "Add regression test",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [1],
            },
        ],
        "refactor": [
            {
                "title": "Analyze existing code",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [],
            },
            {
                "title": "Refactor implementation",
                "complexity": "M",
                "assigned_role": "engineer",
                "dependencies": [0],
            },
            {
                "title": "Update tests",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [1],
            },
        ],
        "migration": [
            {
                "title": "Create migration script",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [],
            },
            {
                "title": "Update code references",
                "complexity": "M",
                "assigned_role": "engineer",
                "dependencies": [0],
            },
            {
                "title": "Test upgrade and rollback",
                "complexity": "S",
                "assigned_role": "engineer",
                "dependencies": [1],
            },
        ],
    }

    # Default for custom/unknown templates
    TEMPLATE_TASK_GRAPHS["custom"] = [
        {
            "title": "Implement changes",
            "complexity": "M",
            "assigned_role": "engineer",
            "dependencies": [],
        },
        {
            "title": "Write tests and verify",
            "complexity": "S",
            "assigned_role": "engineer",
            "dependencies": [0],
        },
    ]

    async def _plan_from_template(
        self,
        run_id: uuid.UUID,
        intent: str,
        template: Optional[str] = None,
    ) -> dict:
        """Generate a task graph from templates without calling Claude.

        This enables the platform to work without an ANTHROPIC_API_KEY.
        The generated tasks use the run intent as their description.
        """
        import copy

        template_key = template if template in self.TEMPLATE_TASK_GRAPHS else "feature"
        tasks = copy.deepcopy(self.TEMPLATE_TASK_GRAPHS[template_key])

        # Inject the intent into each task's description
        for task in tasks:
            task["description"] = f"{task['title']}: {intent}"

        task_graph = {"tasks": tasks}

        # Estimate costs
        estimated_cost = self._estimate_cost(task_graph)
        task_graph["estimated_cost_usd"] = estimated_cost

        # Store task graph + create RunTask rows
        await self.run_svc.set_task_graph(run_id, task_graph)

        # Update estimated cost on run
        run = await self.db.get(Run, run_id)
        run.estimated_cost_usd = estimated_cost
        await self.db.flush()

        # Record event
        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_PLAN_GENERATED,
            data={
                "run_id": str(run_id),
                "task_count": len(tasks),
                "estimated_cost_usd": estimated_cost,
                "source": "template",
                "template": template_key,
            },
        )

        # Transition to awaiting approval
        await self.run_svc.change_status(
            run_id, "awaiting_plan_approval"
        )

        return task_graph
