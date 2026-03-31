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

    def __init__(self, db: AsyncSession, session_factory=None):
        self.db = db
        self.events = EventStore(db)
        self.run_svc = RunService(db)
        self._client = None  # Lazy init — only when Claude is actually needed
        if session_factory is None:
            from openclaw.db.engine import async_session_factory
            session_factory = async_session_factory
        self._session_factory = session_factory

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
        """Generate a TaskGraph by dispatching the manager agent.

        The manager agent IS the planner. It gets dispatched into the repo
        with Claude Code, reads the codebase, understands the architecture,
        and creates the task graph using MCP tools.

        This replaces the old blind API call with a codebase-aware agent.

        Flow:
        1. Load run (get intent + team)
        2. Transition run → planning
        3. Find the manager agent for this team
        4. Dispatch manager agent with planning prompt
        5. Manager reads codebase + calls set_run_task_graph MCP tool
        6. Manager transitions run → awaiting_plan_approval
        7. Return the task graph
        """
        from sqlalchemy import select
        from openclaw.db.models import Agent
        from openclaw.agent.runner import AgentRunner

        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        # Transition to planning (if still in draft)
        if run.status == "draft":
            await self.run_svc.change_status(run_id, "planning")

        # Extract template from metadata
        meta = run.run_metadata or {}
        template = meta.get("template")

        # Find the manager agent for this team
        result = await self.db.execute(
            select(Agent).where(
                Agent.team_id == run.team_id,
                Agent.role == "manager",
            ).limit(1)
        )
        manager = result.scalars().first()

        if not manager:
            logger.warning(
                "No manager agent for team %s, falling back to template planning",
                run.team_id,
            )
            return await self._plan_from_template(
                run_id, run.intent, template
            )

        await self.db.commit()  # flush before spawning agent

        # Build the planning prompt for the manager agent
        prompt = self._build_manager_planning_prompt(
            run_id=str(run_id),
            intent=run.intent,
            team_id=str(run.team_id),
            agent_id=str(manager.id),
            template=template,
        )

        # Dispatch the manager agent to plan
        logger.info(
            "Dispatching manager agent %s to plan run %s",
            manager.id, run_id,
        )

        runner = AgentRunner(session_factory=self._session_factory)
        result = await runner.run_agent(
            agent_id=str(manager.id),
            team_id=str(run.team_id),
            prompt_override=prompt,
            run_task_id=0,  # Use 0 for planning phase
        )

        # Get the manager's analysis from stdout
        agent_analysis = result.get("stdout", "")

        if result.get("error") and not agent_analysis:
            logger.error(
                "Manager agent failed to plan run %s: %s",
                run_id, result["error"],
            )
            return await self._plan_from_template(
                run_id, run.intent, template
            )

        # Check if the manager called set_run_task_graph via MCP
        async with self._session_factory() as db2:
            run_check = await db2.get(Run, run_id)
            if run_check and run_check.task_graph and run_check.task_graph.get("tasks"):
                logger.info(
                    "Manager agent set task graph via MCP: %d tasks",
                    len(run_check.task_graph["tasks"]),
                )
                if run_check.status == "planning":
                    svc = RunService(db2)
                    await svc.change_status(run_id, "awaiting_plan_approval")
                    await db2.commit()
                return run_check.task_graph

        # Manager produced analysis but couldn't call MCP tool.
        # Use Claude API to convert the analysis into structured task graph.
        logger.info(
            "Manager agent produced analysis (%d chars), "
            "converting to structured task graph via API",
            len(agent_analysis),
        )
        return await self._convert_analysis_to_task_graph(
            run_id, run.intent, agent_analysis, template
        )

    async def _convert_analysis_to_task_graph(
        self,
        run_id: uuid.UUID,
        intent: str,
        agent_analysis: str,
        template: str | None = None,
    ) -> dict:
        """Convert manager agent's text analysis to structured task graph.

        The manager agent read the codebase and produced an analysis.
        Now we use a quick Claude API call to convert that into the
        structured JSON format needed for RunTasks.
        """
        prompt = (
            "You are converting a software architect's analysis into a structured task graph.\n\n"
            f"ORIGINAL INTENT: {intent}\n\n"
            f"ARCHITECT'S ANALYSIS (from codebase review):\n{agent_analysis}\n\n"
            "Convert this analysis into concrete tasks. Follow the architect's recommendations "
            "for task count, dependencies, and complexity. If the analysis suggests 1-2 tasks, "
            "create 1-2 tasks. Don't add unnecessary tasks.\n\n"
            "IMPORTANT: Include specific file paths mentioned in the analysis. "
            "Maximize parallelism — only add dependencies when truly needed."
        )

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                tools=[TASK_GRAPH_TOOL],
                tool_choice={"type": "tool", "name": "create_task_graph"},
                messages=[{"role": "user", "content": prompt}],
            )

            task_graph = self._extract_task_graph(response)
        except Exception as e:
            logger.warning(
                "Failed to convert analysis to task graph: %s, "
                "falling back to template",
                e,
            )
            return await self._plan_from_template(run_id, intent, template)

        # Estimate costs and store
        estimated_cost = self._estimate_cost(task_graph)
        task_graph["estimated_cost_usd"] = estimated_cost

        await self.run_svc.set_task_graph(run_id, task_graph)

        run = await self.db.get(Run, run_id)
        if run:
            run.estimated_cost_usd = estimated_cost
            await self.db.flush()

        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_PLAN_GENERATED,
            data={
                "run_id": str(run_id),
                "task_count": len(task_graph.get("tasks", [])),
                "estimated_cost_usd": estimated_cost,
                "source": "manager_agent",
            },
        )

        await self.run_svc.change_status(run_id, "awaiting_plan_approval")
        return task_graph

    def _build_manager_planning_prompt(
        self,
        run_id: str,
        intent: str,
        team_id: str,
        agent_id: str,
        template: str | None = None,
    ) -> str:
        """Build the prompt for the manager agent to plan a run.

        The manager agent will:
        1. Read the codebase to understand the project
        2. Decompose the intent into a task graph
        3. Call set_run_task_graph MCP tool
        4. Transition the run to awaiting_plan_approval
        """
        template_hint = ""
        if template and template in RUN_TEMPLATES:
            tmpl = RUN_TEMPLATES[template]
            template_hint = f"\nTemplate hint ({template}): {tmpl['hints']}\n"

        return f"""You are the PLANNING MANAGER for run {run_id}.

YOUR JOB: Read the codebase, understand its structure, then decompose this intent
into a task graph that AI coding agents can execute.

INTENT:
{intent}
{template_hint}
STEP 1 — READ THE CODEBASE:
Before planning, explore the project structure. Look at:
- The directory layout (what folders exist, where code lives)
- Existing patterns (how similar features are implemented)
- Key files that will need to be modified
- Test patterns (how tests are organized)

STEP 2 — DECOMPOSE INTO TASKS:
Create a task graph where:
- Each task is a focused unit of work for ONE agent
- Tasks that CAN run in parallel SHOULD have no dependencies between them
- Only add dependencies when task B truly needs task A's output
- Descriptions must include SPECIFIC file paths, function names, patterns to follow
- Keep it minimal — don't create tasks for things that don't need doing
- A simple utility function = 1 task, not 4

SIZING GUIDE:
- S: Single file change, <30 min (add a utility, fix a typo, config change)
- M: Multi-file feature, 30-90 min (new endpoint with tests)
- L: Complex feature, 90-180 min (new subsystem)
- XL: Major feature, 180+ min (rarely needed — split into smaller tasks)

STEP 3 — SUBMIT THE PLAN:
Call the MCP tool to set the task graph:

mcp__entourage__set_run_task_graph(
    run_id="{run_id}",
    tasks=[
        {{
            "title": "...",
            "description": "Specific description with file paths and acceptance criteria",
            "complexity": "S|M|L|XL",
            "assigned_role": "engineer",
            "dependencies": [],
            "integration_hints": ["How this connects to other tasks"]
        }},
        ...
    ]
)

STEP 4 — TRANSITION THE RUN:
After setting the task graph, transition the run:
mcp__entourage__change_task_status is NOT what you need.
Instead the system will auto-transition after you set the task graph.

YOUR IDENTITY:
- agent_id: {agent_id}
- team_id: {team_id}
- run_id: {run_id}

IMPORTANT RULES:
- DO read the codebase first. Your plan quality depends on understanding the project.
- DO maximize parallelism — independent tasks should NOT depend on each other.
- DO include specific file paths in task descriptions.
- DON'T create unnecessary tasks (no "create data models" for a utility function).
- DON'T make everything sequential — find what can run in parallel.
- DON'T skip calling set_run_task_graph — that's your deliverable.

Begin by exploring the project structure, then create the task graph.
"""

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
