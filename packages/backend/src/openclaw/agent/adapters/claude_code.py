"""Claude Code adapter — spawns Claude Code CLI via tmux runtime.

Phase 3: Uses tmux by default for interactive, observable, crash-survivable
agent sessions. Falls back to --print subprocess when tmux is unavailable.

Claude Code CLI supports:
- Interactive mode: agent stays alive, receives prompts via stdin
- --print: Non-interactive fire-and-forget (legacy fallback)
- --mcp-config: JSON describing MCP servers to connect to
- --allowedTools: Restrict which tools the agent can use
- --max-turns: Safety limit on agentic loop iterations
"""

import os
import shutil

from openclaw.agent.adapters.base import AdapterConfig, AdapterResult, AgentAdapter


class ClaudeCodeAdapter(AgentAdapter):
    """Adapter for Claude Code CLI (claude command)."""

    # Common install locations to search beyond PATH
    _EXTRA_SEARCH_PATHS = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.npm-global/bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]

    @property
    def name(self) -> str:
        return "claude_code"

    def _find_claude_binary(self) -> str | None:
        """Locate the claude binary on PATH or common install locations."""
        found = shutil.which("claude")
        if found:
            return found
        # Check common install directories not always on PATH
        for extra_dir in self._EXTRA_SEARCH_PATHS:
            candidate = os.path.join(extra_dir, "claude")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        return None

    def validate_environment(self) -> tuple[bool, str]:
        """Check that the `claude` binary is available."""
        binary = self._find_claude_binary()
        if binary:
            return True, f"Claude Code CLI found at {binary}"
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

    def get_launch_command(
        self, config: AdapterConfig, mcp_config_path: str
    ) -> list[str]:
        """Build the CLI command to launch Claude Code (interactive mode).

        Returns the command list WITHOUT --print so the agent stays alive
        and can receive follow-up messages via the runtime.
        """
        claude_bin = self._find_claude_binary()
        if not claude_bin:
            raise RuntimeError("Claude Code CLI not found on PATH.")

        return [
            claude_bin,
            "--mcp-config", mcp_config_path,
            "--allowedTools", "mcp__entourage__*",
            "--max-turns", "100",
        ]

    def get_environment(self, config: AdapterConfig) -> dict[str, str]:
        """Environment variables to pass to the agent process."""
        return {
            "ENTOURAGE_AGENT_ID": config.agent_id,
            "ENTOURAGE_TEAM_ID": config.team_id,
            "ENTOURAGE_TASK_ID": str(config.task_id),
            **config.env_overrides,
        }

    async def run(self, prompt: str, config: AdapterConfig) -> AdapterResult:
        """Spawn Claude Code — uses tmux runtime for interactive sessions.

        Phase 3: Agents run in tmux by default (observable, crash-survivable,
        can receive follow-up messages). Falls back to --print subprocess
        only when tmux is unavailable.
        """
        config_path, config_dir = self._write_mcp_config(config)

        claude_bin = self._find_claude_binary()
        if not claude_bin:
            return AdapterResult(
                exit_code=-1, stdout="", stderr="",
                duration_seconds=0.0,
                error="Claude Code CLI not found on PATH.",
            )

        # Try tmux runtime first (interactive, observable)
        try:
            return await self._run_interactive(
                prompt, config, claude_bin, config_path, config_dir
            )
        except Exception as e:
            import logging
            logger = logging.getLogger("openclaw.agent.adapters.claude_code")
            logger.warning(
                "Tmux runtime failed (%s), falling back to --print mode", e,
            )
            # Fall back to --print subprocess
            try:
                return await self._run_print_mode(
                    prompt, config, claude_bin, config_path
                )
            finally:
                self._cleanup_mcp_config(config_path, config_dir)

    async def _run_interactive(
        self,
        prompt: str,
        config: AdapterConfig,
        claude_bin: str,
        config_path: str,
        config_dir: str,
    ) -> AdapterResult:
        """Run Claude Code interactively in a tmux session.

        The agent is launched without --print so it stays alive. The prompt
        is delivered post-launch via tmux load-buffer (handles arbitrary
        length without truncation).

        The method blocks until the agent exits or times out, then returns
        the captured pane output as AdapterResult.
        """
        import asyncio
        import time
        import logging
        from openclaw.agent.runtime import get_runtime, RuntimeConfig

        logger = logging.getLogger("openclaw.agent.adapters.claude_code")

        runtime = get_runtime("tmux")
        valid, msg = runtime.validate()
        if not valid:
            raise RuntimeError(f"Tmux not available: {msg}")

        # Write prompt to file and create a launcher script.
        # This avoids ALL shell quoting issues — the script reads
        # the prompt from file, so no escaping needed.
        prompt_path = os.path.join(config_dir, "prompt.txt")
        with open(prompt_path, "w") as pf:
            pf.write(prompt)

        # Output file — captures stdout alongside tmux pane display
        output_path = os.path.join(config_dir, "output.txt")

        launcher_path = os.path.join(config_dir, "run-agent.sh")
        with open(launcher_path, "w") as lf:
            lf.write("#!/bin/bash\n")
            # Use tee to capture stdout to file AND display in tmux
            lf.write(f'"{claude_bin}" --print \\\n')
            lf.write(f'  --mcp-config "{config_path}" \\\n')
            lf.write(f'  --allowedTools "mcp__entourage__*" \\\n')
            lf.write(f'  --max-turns 100 \\\n')
            lf.write(f'  "$(cat \'{prompt_path}\')" 2>&1 | tee "{output_path}"\n')
        os.chmod(launcher_path, 0o755)

        cmd = [launcher_path]
        env = self.get_environment(config)
        session_id = f"task-{config.task_id}"

        rt_config = RuntimeConfig(
            session_id=session_id,
            command=cmd,
            cwd=config.working_directory,
            env=env,
            startup_delay_seconds=0.0,
        )

        # Spawn the agent in tmux
        rt_session = await runtime.create(rt_config)

        # Poll until exit or timeout
        start = time.monotonic()
        while True:
            alive = await runtime.is_alive(rt_session)
            if not alive:
                break

            elapsed = time.monotonic() - start
            if elapsed > config.timeout_seconds:
                output = await runtime.read_output(rt_session, 500)
                await runtime.kill(rt_session)
                self._cleanup_mcp_config(config_path, config_dir)
                return AdapterResult(
                    exit_code=-1,
                    stdout=output,
                    stderr="",
                    duration_seconds=elapsed,
                    error=f"Agent timed out after {config.timeout_seconds:.0f}s",
                )

            await asyncio.sleep(5.0)

        duration = time.monotonic() - start

        # Read stdout from output file (preferred) or pane capture (fallback)
        output = ""
        try:
            with open(output_path, "r") as of:
                output = of.read()
        except (FileNotFoundError, OSError):
            output = await runtime.read_output(rt_session, 500)

        # Don't clean up MCP config yet — caller may need output_path
        # self._cleanup_mcp_config(config_path, config_dir)

        return AdapterResult(
            exit_code=0,
            stdout=output,
            stderr="",
            duration_seconds=duration,
        )

    async def _run_print_mode(
        self,
        prompt: str,
        config: AdapterConfig,
        claude_bin: str,
        config_path: str,
    ) -> AdapterResult:
        """Fallback: run Claude Code with --print (fire-and-forget)."""
        cmd = [
            claude_bin,
            "--print",
            "--mcp-config", config_path,
            "--allowedTools", "mcp__entourage__*",
            "--max-turns", "100",
            prompt,
        ]
        return await self._run_subprocess(cmd, config)
