"""Agent adapter base — pluggable interface for coding agent backends.

Entourage dispatches to existing coding agents (Claude Code, Codex, Aider)
and provides orchestration (tasks, reviews, HITL, costs) via MCP server.

Each adapter knows how to:
1. Spawn a specific coding agent (subprocess or tmux)
2. Configure it with our MCP server for Entourage tools
3. Build a prompt with task context + MCP tool instructions
4. Handle timeouts and cleanup

Common utilities (MCP config, prompt sections) live here to avoid duplication.
"""

import asyncio
import json
import os
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdapterConfig:
    """Configuration passed to every adapter run.

    Learn: This is a value object — all info the adapter needs to
    spawn the coding agent in the right context.
    """

    # MCP server connection
    mcp_server_command: list[str]  # e.g. ["node", "/path/to/dist/index.js"]
    api_url: str  # OPENCLAW_API_URL for MCP server's HTTP client

    # Working context
    working_directory: str  # worktree path for the task

    # Entourage identifiers (passed to the agent via prompt)
    agent_id: str
    team_id: str
    task_id: int

    # Limits
    timeout_seconds: float = 1800.0  # 30 min default

    # Security restrictions
    write_path_allowlist: list[str] = field(default_factory=list)
    network_allowlist: list[str] = field(default_factory=list)

    # Extra env vars for the subprocess
    env_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class AdapterResult:
    """Structured result from running a coding agent.

    Learn: Mirrors GitResult from git_service.py for consistency.
    Every adapter run produces this, regardless of the backend.
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.error is None


class AgentAdapter(ABC):
    """Abstract base for coding agent adapters.

    Learn: Implement this to add support for a new coding agent.
    The adapter is responsible for subprocess lifecycle — spawning,
    monitoring, timeout, and cleanup.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Adapter identifier, e.g. 'claude_code', 'codex', 'aider'."""

    @abstractmethod
    async def run(self, prompt: str, config: AdapterConfig) -> AdapterResult:
        """Execute the coding agent with the given prompt.

        Must handle:
        - Building the subprocess command
        - Configuring MCP server connection
        - Starting + monitoring the subprocess
        - Timeout with proc.kill()
        - Returning structured AdapterResult
        """

    @abstractmethod
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
        """Construct the prompt / initial instruction for the coding agent.

        Must include:
        - Task context (title, description)
        - Entourage MCP tool usage instructions
        - Agent identity (agent_id, team_id) for tool calls
        - Team conventions (coding standards, architecture decisions)
        - Previous context from earlier runs (context carryover)

        The role param ("engineer", "manager", or "reviewer") allows
        adapters to produce different prompts for different agent roles.
        """

    def validate_environment(self) -> tuple[bool, str]:
        """Check if this adapter's coding agent is installed.

        Returns (is_valid, message). Override to check for
        specific binaries on PATH.
        """
        return True, "ok"

    # ─── Shared utilities (used by all adapters) ─────────────

    def _write_mcp_config(self, config: AdapterConfig) -> tuple[str, str]:
        """Write MCP config to a temp file. Returns (config_path, config_dir).

        All adapters need to tell their coding agent how to connect to
        our MCP server. This standardizes the config format.
        """
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
        config_dir = tempfile.mkdtemp(prefix="entourage-mcp-")
        config_path = os.path.join(config_dir, "mcp-config.json")
        with open(config_path, "w") as f:
            json.dump(mcp_config, f)
        return config_path, config_dir

    def _cleanup_mcp_config(self, config_path: str, config_dir: str) -> None:
        """Remove temp MCP config files."""
        try:
            os.unlink(config_path)
            os.rmdir(config_dir)
        except OSError:
            pass

    def _build_conventions_section(
        self, conventions: list[dict] | None, prefix: str = "Follow these team standards:"
    ) -> str:
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

    async def _run_subprocess(
        self,
        cmd: list[str],
        config: AdapterConfig,
    ) -> AdapterResult:
        """Helper: run a subprocess with timeout handling.

        Learn: Follows the exact pattern from git_service.py _run_git
        (asyncio.create_subprocess_exec + wait_for + kill on timeout).
        All adapters should use this instead of reimplementing subprocess logic.
        """
        env = {**os.environ, **config.env_overrides}

        start_time = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=config.working_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()  # ensure process is reaped
            duration = time.monotonic() - start_time
            return AdapterResult(
                exit_code=-1,
                stdout="",
                stderr="",
                duration_seconds=duration,
                error=f"Agent timed out after {config.timeout_seconds:.0f}s",
            )

        duration = time.monotonic() - start_time
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        return AdapterResult(
            exit_code=proc.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            error=None if proc.returncode == 0 else f"Process exited with code {proc.returncode}",
        )
