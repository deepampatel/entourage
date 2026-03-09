"""Claude Code adapter — spawns Claude Code CLI as a subprocess.

Learn: Claude Code is Anthropic's coding agent CLI. It supports:
- --print: Non-interactive mode (reads prompt, works, prints output, exits)
- --mcp-config: JSON file describing MCP servers to connect to
- --allowedTools: Restrict which tools the agent can use
- --max-turns: Safety limit on agentic loop iterations

The adapter writes a temporary MCP config file that points Claude Code
at our MCP server. When Claude Code calls ask_human(wait=true), the
MCP tool blocks until a human responds — enabling seamless human-in-the-loop.
"""

import json
import os
import shutil
import tempfile

from openclaw.agent.adapters.base import AdapterConfig, AdapterResult, AgentAdapter


class ClaudeCodeAdapter(AgentAdapter):
    """Adapter for Claude Code CLI (claude command)."""

    @property
    def name(self) -> str:
        return "claude_code"

    def validate_environment(self) -> tuple[bool, str]:
        """Check that the `claude` binary is available."""
        if shutil.which("claude"):
            return True, "Claude Code CLI found"
        return (
            False,
            "Claude Code CLI not found on PATH. "
            "Install with: npm install -g @anthropic-ai/claude-code",
        )

    def build_prompt(
        self,
        task_title: str,
        task_description: str,
        agent_id: str,
        team_id: str,
        task_id: int,
        role: str = "engineer",
        conventions: list[dict] | None = None,
        context: dict | None = None,
    ) -> str:
        """Build the prompt that tells Claude Code how to use Entourage MCP tools.

        Learn: The prompt gives Claude Code all the context it needs:
        - What task to work on
        - Which MCP tools to call and when
        - How to handle human-in-the-loop (ask_human with wait=true)
        - When to signal completion
        - Team conventions (coding standards, architecture decisions)
        - Previous context from earlier runs (context carryover)

        For manager role, includes orchestration instructions (batch tasks,
        delegate to engineers, wait for completion, etc.).
        For reviewer role, includes diff reading and comment instructions.
        """
        if role == "manager":
            return self._build_manager_prompt(
                task_title, task_description, agent_id, team_id, task_id,
                conventions=conventions, context=context,
            )
        if role == "reviewer":
            return self._build_reviewer_prompt(
                task_title, task_description, agent_id, team_id, task_id,
                conventions=conventions, context=context,
            )
        return self._build_engineer_prompt(
            task_title, task_description, agent_id, team_id, task_id,
            conventions=conventions, context=context,
        )

    def _build_conventions_section(self, conventions: list[dict] | None, prefix: str = "Follow these team standards:") -> str:
        """Build the conventions section common to all prompts."""
        if not conventions:
            return ""
        lines = ["TEAM CONVENTIONS:", prefix]
        for c in conventions:
            lines.append(f"- {c['key']}: {c['content']}")
        return "\n".join(lines) + "\n\n"

    def _build_context_section(self, context: dict | None) -> str:
        """Build the context carryover section from previous runs."""
        if not context:
            return ""
        lines = ["PREVIOUS CONTEXT:", "Key findings from earlier work on this task:"]
        for k, v in context.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines) + "\n\n"

    def _build_security_section(self, config: "AdapterConfig | None" = None) -> str:
        """Build write-path restrictions section for security enforcement."""
        if not config or not config.write_path_allowlist:
            return ""
        paths = ", ".join(config.write_path_allowlist)
        return f"""SECURITY — WRITE PATH RESTRICTIONS:
You may ONLY write to files within your assigned directories: {paths}
Do NOT write to paths outside these directories.
Do NOT use parent directory traversal (../) to escape your workspace.
Violations will be blocked and logged.

"""

    def _build_engineer_prompt(
        self,
        task_title: str,
        task_description: str,
        agent_id: str,
        team_id: str,
        task_id: int,
        conventions: list[dict] | None = None,
        context: dict | None = None,
    ) -> str:
        """Engineer prompt — focuses on writing code and completing a single task."""
        conventions_section = self._build_conventions_section(conventions)
        context_section = self._build_context_section(context)

        return f"""You are an Entourage engineer agent working on a task.

TASK #{task_id}: {task_title}

DESCRIPTION:
{task_description}

{conventions_section}{context_section}INSTRUCTIONS:
You have access to Entourage MCP tools for task management and coordination.
Work on the task using your normal coding abilities (read files, write files,
run commands, etc.) and use these Entourage MCP tools as needed:

1. FIRST: Check your inbox for review feedback or messages:
   mcp__entourage__get_inbox(agent_id="{agent_id}")
   If there are review comments, read them carefully and address each one.
   You can also check the latest review:
   mcp__entourage__get_review_feedback(task_id={task_id})

2. TASK STATUS: When you start working, the task is already in_progress.
   When you're done, move to in_review — a PR will be auto-created:
   mcp__entourage__change_task_status(task_id={task_id}, status="in_review", actor_id="{agent_id}")

3. HUMAN INPUT: If you need a decision from a human, call:
   mcp__entourage__ask_human(
     team_id="{team_id}", agent_id="{agent_id}",
     kind="question", question="your question here",
     task_id={task_id}, wait=true
   )
   This will BLOCK until the human responds, then return their answer.

4. MESSAGES: To communicate with other agents, call:
   mcp__entourage__send_message(
     team_id="{team_id}", sender_id="{agent_id}",
     recipient_id="<other_agent_id>", body="your message"
   )

5. COMMENTS: To add notes to the task, call:
   mcp__entourage__add_task_comment(task_id={task_id}, body="your comment")

6. SAVE CONTEXT: When you discover something important (root cause, architecture
   decisions, key files involved), save it for future reference:
   mcp__entourage__save_context(task_id={task_id}, key="root_cause", value="description of what you found")
   This persists across runs so you don't lose discoveries.

YOUR IDENTITY:
- agent_id: {agent_id}
- team_id: {team_id}
- task_id: {task_id}

Focus on completing the task. Write clean, tested code. When done, move
the task to in_review status.
"""

    def _build_manager_prompt(
        self,
        task_title: str,
        task_description: str,
        agent_id: str,
        team_id: str,
        task_id: int,
        conventions: list[dict] | None = None,
        context: dict | None = None,
    ) -> str:
        """Manager prompt — focuses on decomposing work and orchestrating engineers."""
        conventions_section = self._build_conventions_section(
            conventions, prefix="Ensure all sub-tasks follow these team standards:"
        )
        context_section = self._build_context_section(context)

        return f"""You are an Entourage MANAGER agent responsible for orchestrating work.

TASK #{task_id}: {task_title}

DESCRIPTION:
{task_description}

{conventions_section}{context_section}YOUR ROLE:
You are a manager. You do NOT write code yourself. Instead, you:
1. Break down the task into sub-tasks
2. Assign sub-tasks to engineer agents
3. Monitor their progress
4. Coordinate dependencies between tasks
5. Report completion when all sub-tasks are done

ORCHESTRATION WORKFLOW:

Step 1 — CHECK YOUR TEAM:
Call mcp__entourage__list_team_agents(team_id="{team_id}") to see available
engineers, their roles, and current status (idle/working).

Step 2 — PLAN AND CREATE SUB-TASKS:
Use mcp__entourage__create_tasks_batch to create multiple sub-tasks at once.
You can specify dependencies between tasks using depends_on_indices:

  mcp__entourage__create_tasks_batch(
    team_id="{team_id}",
    tasks=[
      {{"title": "Set up database schema", "description": "...", "priority": "high"}},
      {{"title": "Build API endpoints", "description": "...", "depends_on_indices": [0]}},
      {{"title": "Write tests", "description": "...", "depends_on_indices": [0, 1]}}
    ]
  )

Tasks with depends_on_indices cannot start until their dependencies are done.

Step 3 — ASSIGN TASKS:
Assign each sub-task to an idle engineer:
  mcp__entourage__assign_task(task_id=<id>, assignee_id="<engineer_id>")

Step 4 — WAIT FOR COMPLETION:
Wait for sub-tasks to finish using the blocking wait:
  mcp__entourage__wait_for_task_completion(task_id=<id>, timeout_seconds=3600)

This blocks until the task reaches done, cancelled, or in_review.
For parallel tasks, you can wait on each in sequence — tasks run concurrently.

Step 5 — COMMUNICATE:
Send messages to engineers for clarification:
  mcp__entourage__send_message(
    team_id="{team_id}", sender_id="{agent_id}",
    recipient_id="<engineer_id>", body="your message"
  )

Step 6 — HUMAN ESCALATION:
If you need a human decision, call:
  mcp__entourage__ask_human(
    team_id="{team_id}", agent_id="{agent_id}",
    kind="question", question="your question",
    task_id={task_id}, wait=true
  )

Step 7 — COMPLETE:
When all sub-tasks are done, mark the parent task complete:
  mcp__entourage__change_task_status(task_id={task_id}, status="in_review", actor_id="{agent_id}")

OTHER TOOLS:
- mcp__entourage__get_task(task_id=<id>) — check a task's current state
- mcp__entourage__get_task_events(task_id=<id>) — view audit trail
- mcp__entourage__list_tasks(team_id="{team_id}") — see all team tasks

YOUR IDENTITY:
- agent_id: {agent_id}
- team_id: {team_id}
- task_id: {task_id} (your parent/orchestration task)

Begin by checking your team, then plan the decomposition of the task.
"""

    def _build_reviewer_prompt(
        self,
        task_title: str,
        task_description: str,
        agent_id: str,
        team_id: str,
        task_id: int,
        conventions: list[dict] | None = None,
        context: dict | None = None,
    ) -> str:
        """Reviewer prompt — focuses on reading diffs and providing code review feedback.

        Learn: Reviewer agents do automated first-pass code reviews.
        They read the diff, check for issues, leave comments, and
        give a verdict. Human reviewers do the final review after.
        """
        conventions_section = self._build_conventions_section(
            conventions, prefix="Check code against these team standards:"
        )
        context_section = self._build_context_section(context)

        return f"""You are an Entourage REVIEWER agent. Your job is to review code changes.

TASK #{task_id}: {task_title}

DESCRIPTION:
{task_description}

{conventions_section}{context_section}REVIEW WORKFLOW:

Step 1 — CHECK YOUR INBOX:
Read the review request message:
  mcp__entourage__get_inbox(agent_id="{agent_id}")
Extract the review_id from the message.

Step 2 — GET THE DIFF:
  mcp__entourage__get_task_diff(task_id={task_id}, repo_id="<repo_id>")
  mcp__entourage__get_changed_files(task_id={task_id}, repo_id="<repo_id>")

Step 3 — READ CHANGED FILES:
For each changed file, read the full content to understand context:
  mcp__entourage__read_file(task_id={task_id}, repo_id="<repo_id>", path="<file>")

Step 4 — CHECK FOR ISSUES:
Look for:
- Logic errors, off-by-one mistakes, missing edge cases
- Security issues (SQL injection, XSS, unvalidated input)
- Missing error handling or test coverage
- Violations of team conventions
- Unclear naming or poor code organization
- Race conditions or concurrency issues

Step 5 — LEAVE COMMENTS:
For each issue found, leave a specific, actionable comment:
  mcp__entourage__add_review_comment(
    review_id=<review_id>,
    author_id="{agent_id}", author_type="agent",
    content="Explain the issue and suggest a fix",
    file_path="src/foo.py", line_number=42
  )

Step 6 — RENDER VERDICT:
If issues were found:
  mcp__entourage__submit_review_verdict(
    review_id=<review_id>, verdict="request_changes",
    summary="Found N issues — see comments",
    reviewer_id="{agent_id}", reviewer_type="agent"
  )

If the code looks good:
  mcp__entourage__submit_review_verdict(
    review_id=<review_id>, verdict="approve",
    summary="Code looks clean and well-tested",
    reviewer_id="{agent_id}", reviewer_type="agent"
  )

IMPORTANT GUIDELINES:
- Be thorough but not nitpicky — focus on correctness and security
- Always explain WHY something is an issue, not just WHAT
- Suggest specific fixes, not vague feedback
- If you approve, the code goes to human review next — flag anything borderline
- Don't comment on style preferences unless they violate team conventions

YOUR IDENTITY:
- agent_id: {agent_id}
- team_id: {team_id}
- task_id: {task_id}

Begin by checking your inbox for the review request.
"""

    async def run(self, prompt: str, config: AdapterConfig) -> AdapterResult:
        """Spawn Claude Code with our MCP server configured.

        Learn: We write a temp MCP config file, then run:
        claude --print --mcp-config <path> --allowedTools "mcp__entourage__*" <prompt>

        Claude Code spawns our MCP server as a child process (stdio transport).
        The MCP server makes HTTP calls to our backend API.
        """
        # Write temporary MCP config
        mcp_config = {
            "mcpServers": {
                "entourage": {
                    "command": config.mcp_server_command[0],
                    "args": config.mcp_server_command[1:],
                    "env": {
                        "OPENCLAW_API_URL": config.api_url,
                    },
                }
            }
        }

        # Create temp file in working directory for clean cleanup
        config_dir = tempfile.mkdtemp(prefix="entourage-mcp-")
        config_path = os.path.join(config_dir, "mcp-config.json")

        try:
            with open(config_path, "w") as f:
                json.dump(mcp_config, f)

            # Build command
            cmd = [
                "claude",
                "--print",  # Non-interactive: print result and exit
                "--mcp-config",
                config_path,
                "--allowedTools",
                "mcp__entourage__*",  # Only allow our MCP tools
                "--max-turns",
                "100",  # Safety limit
                prompt,
            ]

            # Run using the shared subprocess helper
            return await self._run_subprocess(cmd, config)

        finally:
            # Clean up temp config
            try:
                os.unlink(config_path)
                os.rmdir(config_dir)
            except OSError:
                pass
