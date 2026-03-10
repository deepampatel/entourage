"""Contract builder — generates typed interface contracts from a TaskGraph.

Phase 2A: When tasks run in parallel, contracts prevent interface collisions.
Uses the Anthropic API tool_use pattern (same as PlannerService) to generate
typed contracts (API, Type, Event, Database) from the task graph.

Agents must acknowledge (lock) contracts before starting work.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import anthropic

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from openclaw.config import settings
from openclaw.db.models import Contract, Run, RunTask
from openclaw.events.store import EventStore
from openclaw.events.types import (
    RUN_CONTRACTS_GENERATED,
    RUN_CONTRACT_LOCKED,
)
from openclaw.services.run_service import RunService

logger = logging.getLogger("openclaw.services.contract_builder")


# ═══════════════════════════════════════════════════════════
# Contract tool schema (for Claude's tool_use)
# ═══════════════════════════════════════════════════════════

CONTRACT_TOOL = {
    "name": "create_contracts",
    "description": (
        "Generate typed interface contracts for tasks that share boundaries. "
        "Contracts ensure parallel agents agree on interfaces before coding."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "contracts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "contract_type": {
                            "type": "string",
                            "enum": ["api", "type", "event", "database"],
                            "description": (
                                "api: Function/endpoint signatures. "
                                "type: Shared data type definitions. "
                                "event: Async event schemas. "
                                "database: Shared table/column definitions."
                            ),
                        },
                        "name": {
                            "type": "string",
                            "description": (
                                "Unique name for this contract, e.g. "
                                "'UserService.get_by_email' or 'UserCreatedEvent'"
                            ),
                        },
                        "producer_task_index": {
                            "type": "integer",
                            "description": (
                                "Zero-based index of the task that produces/defines "
                                "this interface."
                            ),
                        },
                        "consumer_task_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": (
                                "Zero-based indices of tasks that consume/depend on "
                                "this interface."
                            ),
                        },
                        "specification": {
                            "type": "object",
                            "description": (
                                "Type-specific contract specification. For api: "
                                "{function_name, parameters, return_type, module_path}. "
                                "For type: {type_name, fields, module_path}. "
                                "For event: {event_name, payload_schema}. "
                                "For database: {table_name, columns}."
                            ),
                        },
                    },
                    "required": [
                        "contract_type",
                        "name",
                        "producer_task_index",
                        "specification",
                    ],
                },
            },
        },
        "required": ["contracts"],
    },
}

CONTRACT_SYSTEM_PROMPT = """\
You are an API design expert. Given a task graph for a software project, \
identify all interface boundaries between tasks that will run in parallel \
and generate precise typed contracts.

For each boundary between tasks, produce a contract of one of these types:
- api: Function or HTTP endpoint signatures (function_name, parameters, return_type, module_path)
- type: Shared data type definitions (type_name, fields with name/type/optional, module_path)
- event: Async event schemas (event_name, payload_schema as JSON Schema)
- database: Shared table/column definitions (table_name, columns with name/type/nullable/pk)

Be precise and minimal. Only generate contracts for actual shared interfaces \
between tasks. Agents will be required to match these contracts exactly.

If no boundaries exist between tasks (all tasks are independent), return an \
empty contracts array.
"""


# ═══════════════════════════════════════════════════════════
# Service
# ═══════════════════════════════════════════════════════════


class ContractBuilder:
    """Generates typed contracts from a TaskGraph using Claude.

    Uses the same Anthropic API tool_use pattern as PlannerService.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventStore(db)
        self.run_svc = RunService(db)
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # ─── Public API ───────────────────────────────────────

    async def generate_contracts(
        self, run_id: uuid.UUID
    ) -> list[Contract]:
        """Generate contracts from the run's task_graph.

        1. Load run and its task_graph
        2. Check if contracts are needed (tasks share boundaries)
        3. Transition run → contracting
        4. Call Claude with CONTRACT_TOOL schema
        5. Create Contract rows in DB
        6. Store raw contract set in Run.contract_set JSONB
        7. Transition run → awaiting_plan_approval
        """
        run = await self.db.get(Run, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        task_graph = run.task_graph
        if not task_graph or not task_graph.get("tasks"):
            raise ValueError(f"Run {run_id} has no task_graph")

        tasks_data = task_graph["tasks"]

        # Check if contracts are actually needed
        if not self._should_generate_contracts(tasks_data):
            logger.info(
                "Run %s: no inter-task boundaries, skipping contracts",
                run_id,
            )
            return []

        # Transition to contracting
        await self.run_svc.change_status(run_id, "contracting")

        # Load run tasks for context
        result = await self.db.execute(
            select(RunTask)
            .where(RunTask.run_id == run_id)
            .order_by(RunTask.id)
        )
        ptasks = list(result.scalars().all())

        # Build prompt
        prompt = self._build_contract_prompt(tasks_data)

        # Call Claude
        logger.info("Generating contracts for run %s", run_id)
        response = await self.client.messages.create(
            model=settings.default_agent_model,
            max_tokens=4096,
            system=CONTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[CONTRACT_TOOL],
            tool_choice={"type": "tool", "name": "create_contracts"},
        )

        # Extract contracts from tool call
        raw_contracts = self._extract_contracts(response)

        # Create Contract rows
        contract_rows: list[Contract] = []
        for c in raw_contracts:
            # Map producer_task_index to run_task_id
            producer_idx = c.get("producer_task_index", 0)
            ptask_id = ptasks[producer_idx].id if producer_idx < len(ptasks) else None

            row = Contract(
                run_id=run_id,
                run_task_id=ptask_id,
                contract_type=c["contract_type"],
                name=c["name"],
                specification=c["specification"],
            )
            self.db.add(row)
            contract_rows.append(row)

        # Store raw contract set on run
        run.contract_set = {"contracts": raw_contracts}
        flag_modified(run, "contract_set")

        # Record event
        await self.events.append(
            stream_id=f"run:{run_id}",
            event_type=RUN_CONTRACTS_GENERATED,
            data={
                "run_id": str(run_id),
                "contract_count": len(contract_rows),
            },
        )

        await self.db.commit()

        # Transition to awaiting_plan_approval
        await self.run_svc.change_status(
            run_id, "awaiting_plan_approval"
        )

        logger.info(
            "Generated %d contracts for run %s",
            len(contract_rows),
            run_id,
        )
        return contract_rows

    async def lock_contract(
        self, contract_id: int, agent_id: uuid.UUID
    ) -> Contract:
        """Agent acknowledges a contract before starting work."""
        contract = await self.db.get(Contract, contract_id)
        if not contract:
            raise ValueError(f"Contract {contract_id} not found")

        if contract.locked:
            # Idempotent — already locked
            return contract

        contract.locked = True
        contract.locked_by = agent_id
        contract.locked_at = datetime.now(timezone.utc)

        await self.events.append(
            stream_id=f"run:{contract.run_id}",
            event_type=RUN_CONTRACT_LOCKED,
            data={
                "run_id": str(contract.run_id),
                "contract_id": contract.id,
                "contract_name": contract.name,
                "agent_id": str(agent_id),
            },
        )
        await self.db.commit()
        return contract

    async def get_contracts(
        self, run_id: uuid.UUID
    ) -> list[Contract]:
        """List all contracts for a run."""
        result = await self.db.execute(
            select(Contract)
            .where(Contract.run_id == run_id)
            .order_by(Contract.id)
        )
        return list(result.scalars().all())

    async def get_contract(self, contract_id: int) -> Optional[Contract]:
        """Get a single contract by ID."""
        return await self.db.get(Contract, contract_id)

    # ─── Helpers ──────────────────────────────────────────

    @staticmethod
    def _should_generate_contracts(tasks_data: list[dict]) -> bool:
        """Check if contracts are needed.

        Returns True when 2+ tasks share integration_hints, meaning
        they have interface boundaries that need to be coordinated.
        """
        if len(tasks_data) < 2:
            return False

        # Collect all hints and check for overlaps
        hint_owners: dict[str, list[int]] = {}
        for i, task in enumerate(tasks_data):
            for hint in task.get("integration_hints", []):
                hint_owners.setdefault(hint, []).append(i)

        # If any hint is shared by 2+ tasks, we need contracts
        return any(len(owners) >= 2 for owners in hint_owners.values())

    def _build_contract_prompt(self, tasks_data: list[dict]) -> str:
        """Build the prompt for Claude to generate contracts."""
        lines = ["## Task Graph\n"]
        for i, task in enumerate(tasks_data):
            lines.append(f"### Task {i}: {task['title']}")
            lines.append(f"**Description:** {task.get('description', '')}")
            lines.append(f"**Role:** {task.get('assigned_role', 'engineer')}")
            deps = task.get("dependencies", [])
            if deps:
                lines.append(f"**Depends on:** Tasks {deps}")
            hints = task.get("integration_hints", [])
            if hints:
                lines.append(f"**Integration hints:** {', '.join(hints)}")
            lines.append("")

        lines.append(
            "Identify all interface boundaries between these tasks and "
            "generate typed contracts. Focus on shared data types, "
            "function signatures, event schemas, and database schemas "
            "that multiple tasks need to agree on."
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_contracts(response) -> list[dict]:
        """Extract contracts from Claude's tool_use response."""
        for block in response.content:
            if block.type == "tool_use" and block.name == "create_contracts":
                return block.input.get("contracts", [])
        return []
