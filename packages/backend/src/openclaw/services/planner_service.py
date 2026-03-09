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
from openclaw.db.models import Pipeline
from openclaw.events.store import EventStore
from openclaw.events.types import PIPELINE_PLAN_GENERATED, PIPELINE_STATUS_CHANGED
from openclaw.services.pipeline_service import PipelineService

logger = logging.getLogger("openclaw.services.planner")


# ═══════════════════════════════════════════════════════════
# Pipeline Templates
# ═══════════════════════════════════════════════════════════

PIPELINE_TEMPLATES: dict[str, dict[str, object]] = {
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
    """Decomposes a human intent into a TaskGraph using Claude."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)
        self.pipeline_svc = PipelineService(db)
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def plan(self, pipeline_id: uuid.UUID) -> dict:
        """Generate a TaskGraph for a pipeline's intent.

        1. Load pipeline (get intent)
        2. Transition pipeline → planning
        3. Call Claude with tool_use for structured TaskGraph output
        4. Validate output
        5. Estimate cost per task
        6. Store task_graph in pipeline, create PipelineTask rows
        7. Transition pipeline → awaiting_plan_approval
        """
        pipeline = await self.db.get(Pipeline, pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        # Transition to planning (if still in draft)
        if pipeline.status == "draft":
            await self.pipeline_svc.change_status(pipeline_id, "planning")

        # Extract template from metadata (if set during creation)
        meta = pipeline.pipeline_metadata or {}
        template = meta.get("template")

        # Build prompt and call Claude
        prompt = self._build_planning_prompt(
            pipeline.intent, template=template
        )

        logger.info("Calling Claude to plan pipeline %s", pipeline_id)
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

        # Store task graph + create PipelineTask rows
        await self.pipeline_svc.set_task_graph(pipeline_id, task_graph)

        # Update estimated cost on pipeline
        pipeline = await self.db.get(Pipeline, pipeline_id)
        pipeline.estimated_cost_usd = estimated_cost
        await self.db.flush()

        # Record event
        await self.events.append(
            stream_id=f"pipeline:{pipeline_id}",
            event_type=PIPELINE_PLAN_GENERATED,
            data={
                "pipeline_id": str(pipeline_id),
                "task_count": len(task_graph.get("tasks", [])),
                "estimated_cost_usd": estimated_cost,
            },
        )

        # Transition to awaiting approval
        await self.pipeline_svc.change_status(
            pipeline_id, "awaiting_plan_approval"
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
        if template and template in PIPELINE_TEMPLATES:
            tmpl = PIPELINE_TEMPLATES[template]
            parts.append(
                f"Pipeline template: {template}\n"
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
