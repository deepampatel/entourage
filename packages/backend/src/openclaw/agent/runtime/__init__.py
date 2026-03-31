"""Runtime layer — manages HOW agent processes are spawned and observed.

Runtimes are separate from adapters:
- Adapter: WHICH agent to run (Claude Code, Codex, Aider) + prompt building
- Runtime: HOW to run it (tmux session, bare process, docker)

Inspired by ComposioHQ/agent-orchestrator's plugin architecture.
"""

from openclaw.agent.runtime.base import Runtime, RuntimeSession, RuntimeConfig
from openclaw.agent.runtime.tmux import TmuxRuntime


def get_runtime(name: str = "tmux") -> Runtime:
    """Get a runtime by name. Currently only tmux is supported."""
    runtimes = {
        "tmux": TmuxRuntime,
    }
    cls = runtimes.get(name)
    if not cls:
        raise ValueError(f"Unknown runtime: {name}. Available: {list(runtimes.keys())}")
    return cls()


__all__ = ["Runtime", "RuntimeSession", "RuntimeConfig", "TmuxRuntime", "get_runtime"]
