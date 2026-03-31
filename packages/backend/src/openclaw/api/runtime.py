"""Runtime API routes — manage tmux sessions for agent execution.

Learn: These routes expose runtime management operations like listing
active tmux sessions. Used by dashboard and CLI tools to monitor
running agent sessions.
"""

from fastapi import APIRouter

from openclaw.agent.runtime.tmux import TmuxRuntime

router = APIRouter()


@router.get("/runtime/sessions")
async def list_sessions():
    """List all active tmux sessions for entourage agents.

    Returns:
        List of session names (strings) with the eo- prefix.
    """
    runtime = TmuxRuntime()
    sessions = await runtime.list_sessions()
    return sessions
