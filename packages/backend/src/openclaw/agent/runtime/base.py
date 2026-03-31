"""Runtime base — abstract interface for agent process management.

A runtime manages the lifecycle of an agent process:
- Create: spawn the process in some execution context
- Send message: deliver text to the agent's stdin
- Read output: capture what the agent has produced
- Check alive: is the process still running?
- Kill: terminate the process
- Attach info: how to observe the agent live

This is the "HOW" layer. Adapters handle "WHAT" (which agent, what prompt).
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuntimeSession:
    """Handle to a running agent process managed by a runtime."""

    session_id: str          # Unique identifier (tmux session name, PID, etc.)
    runtime_type: str        # "tmux" or "process"
    pid: Optional[int] = None
    cwd: Optional[str] = None
    started_at: Optional[float] = None
    env: dict[str, str] = field(default_factory=dict)

    # How to observe this session
    attach_command: Optional[str] = None  # e.g. "tmux attach -t eo-task-42"


@dataclass
class RuntimeConfig:
    """Configuration for creating a runtime session."""

    session_id: str              # Desired session name
    command: list[str]           # Command to execute
    cwd: str                     # Working directory
    env: dict[str, str] = field(default_factory=dict)
    startup_delay_seconds: float = 3.0  # Wait after spawn before sending prompt


class Runtime(ABC):
    """Abstract runtime — manages agent process lifecycle."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Runtime identifier: 'tmux', 'process', etc."""

    @abstractmethod
    async def create(self, config: RuntimeConfig) -> RuntimeSession:
        """Spawn the agent process and return a session handle."""

    @abstractmethod
    async def send_message(self, session: RuntimeSession, message: str) -> bool:
        """Send text to the agent's stdin. Returns True if successful."""

    @abstractmethod
    async def read_output(self, session: RuntimeSession, lines: int = 500) -> str:
        """Capture recent output from the agent."""

    @abstractmethod
    async def is_alive(self, session: RuntimeSession) -> bool:
        """Check if the agent process is still running."""

    @abstractmethod
    async def kill(self, session: RuntimeSession) -> None:
        """Terminate the agent process."""

    def validate(self) -> tuple[bool, str]:
        """Check if this runtime is available on the system."""
        return True, "ok"
