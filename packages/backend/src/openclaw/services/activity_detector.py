"""Agent activity detector — reads Claude Code session files for real-time status.

Instead of only knowing exit_code after a process finishes, this reads Claude Code's
JSONL session logs to determine the agent's CURRENT state: active, idle, stuck, etc.

Inspired by ComposioHQ/agent-orchestrator's activity detection via session file reading.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openclaw.services.activity_detector")


class AgentState(str, Enum):
    """Possible states of a Claude Code agent process."""
    ACTIVE = "active"          # Currently processing (tool calls, thinking)
    IDLE = "idle"              # Waiting for input / between actions
    STUCK = "stuck"            # No activity for too long
    BLOCKED = "blocked"        # Waiting for human input / permission
    EXITED = "exited"          # Process has finished
    UNKNOWN = "unknown"        # Can't determine state


@dataclass
class ActivitySnapshot:
    """Point-in-time snapshot of agent activity."""
    state: AgentState
    last_activity_seconds_ago: float
    last_event_type: Optional[str] = None
    session_file: Optional[str] = None
    details: Optional[str] = None


# Event types that indicate the agent is actively working
_ACTIVE_EVENTS = {
    "assistant", "tool_use", "tool_result",
    "bash", "edit", "write", "read", "glob", "grep",
}

# Event types that indicate the agent is waiting/blocked
_BLOCKED_EVENTS = {
    "permission_request", "human_input_request",
}

# Event types that indicate the session is done
_EXIT_EVENTS = {
    "result", "error", "exit",
}

# Staleness thresholds (seconds)
_ACTIVE_THRESHOLD = 120     # 2 min - still considered active
_STUCK_THRESHOLD = 600      # 10 min - probably stuck


class ActivityDetector:
    """Detect Claude Code agent activity by reading JSONL session files."""

    def __init__(self, claude_projects_dir: Optional[str] = None):
        """Initialize with optional override for Claude projects directory."""
        self._projects_dir = claude_projects_dir or os.path.expanduser(
            "~/.claude/projects"
        )

    def detect(
        self,
        working_directory: str,
        process_alive: bool = True,
    ) -> ActivitySnapshot:
        """Detect the current state of a Claude Code agent.

        Args:
            working_directory: The cwd where Claude Code was launched
            process_alive: Whether the subprocess is still running
        """
        if not process_alive:
            return ActivitySnapshot(
                state=AgentState.EXITED,
                last_activity_seconds_ago=0,
                details="Process not running",
            )

        session_file = self._find_session_file(working_directory)
        if not session_file:
            return ActivitySnapshot(
                state=AgentState.UNKNOWN,
                last_activity_seconds_ago=0,
                details="No session file found",
            )

        try:
            mtime = os.path.getmtime(session_file)
            age = time.time() - mtime
            last_events = self._read_last_events(session_file, count=5)

            if not last_events:
                return ActivitySnapshot(
                    state=AgentState.UNKNOWN,
                    last_activity_seconds_ago=age,
                    session_file=str(session_file),
                    details="Session file empty",
                )

            last_event = last_events[-1]
            event_type = last_event.get("type", "unknown")

            # Determine state from event type + staleness
            state = self._classify(event_type, age, last_events)

            return ActivitySnapshot(
                state=state,
                last_activity_seconds_ago=round(age, 1),
                last_event_type=event_type,
                session_file=str(session_file),
                details=self._summarize(last_event),
            )

        except Exception as e:
            logger.debug(
                "Failed to read session file %s: %s", session_file, e
            )
            return ActivitySnapshot(
                state=AgentState.UNKNOWN,
                last_activity_seconds_ago=0,
                details=f"Error: {e}",
            )

    def _find_session_file(self, working_directory: str) -> Optional[Path]:
        """Find the most recent Claude Code session file for a working directory.

        Claude Code stores sessions in:
          ~/.claude/projects/{encoded_path}/sessions/{session_id}.jsonl

        The directory name is the working directory path with / replaced by -.
        """
        # Claude Code encodes the path by replacing / with -
        # and prefixing with the absolute path
        encoded = working_directory.replace("/", "-").lstrip("-")
        project_dir = Path(self._projects_dir) / encoded

        if not project_dir.exists():
            # Try alternative: just the basename
            project_dir = None
            projects_root = Path(self._projects_dir)
            if projects_root.exists():
                for d in projects_root.iterdir():
                    if d.is_dir() and working_directory.rstrip("/").split("/")[-1] in d.name:
                        project_dir = d
                        break

            if not project_dir:
                return None

        # Find session files
        sessions_dir = project_dir
        session_files = sorted(
            sessions_dir.glob("**/*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        return session_files[0] if session_files else None

    def _read_last_events(
        self, session_file: Path, count: int = 5
    ) -> list[dict]:
        """Read the last N events from a JSONL file (efficient tail read)."""
        events = []
        try:
            # Read from end of file for efficiency
            with open(session_file, "rb") as f:
                # Seek to end
                f.seek(0, 2)
                file_size = f.tell()

                # Read last chunk (most events are <4KB)
                chunk_size = min(file_size, count * 4096)
                f.seek(file_size - chunk_size)
                data = f.read().decode("utf-8", errors="replace")

            # Parse last N lines
            lines = [line.strip() for line in data.split("\n") if line.strip()]
            for line in lines[-count:]:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        except Exception as e:
            logger.debug("Failed to read events from %s: %s", session_file, e)

        return events

    def _classify(
        self,
        event_type: str,
        age_seconds: float,
        events: list[dict],
    ) -> AgentState:
        """Classify agent state from event type and staleness."""
        # Check for exit events
        if event_type in _EXIT_EVENTS:
            return AgentState.EXITED

        # Check for blocked events
        if event_type in _BLOCKED_EVENTS:
            return AgentState.BLOCKED

        # Check staleness
        if age_seconds > _STUCK_THRESHOLD:
            return AgentState.STUCK

        if age_seconds > _ACTIVE_THRESHOLD:
            # Could be stuck or just thinking for a while
            # Check if recent events show a pattern of activity
            recent_types = {e.get("type") for e in events[-3:]}
            if recent_types & _ACTIVE_EVENTS:
                return AgentState.ACTIVE  # Recent activity, just slow
            return AgentState.STUCK

        # Recent activity
        if event_type in _ACTIVE_EVENTS:
            return AgentState.ACTIVE

        return AgentState.IDLE

    def _summarize(self, event: dict) -> str:
        """Create a human-readable summary of the last event."""
        event_type = event.get("type", "unknown")

        if event_type == "tool_use":
            tool = event.get("tool", event.get("name", "unknown"))
            return f"Using tool: {tool}"
        elif event_type == "assistant":
            text = event.get("text", event.get("content", ""))
            if isinstance(text, str) and len(text) > 80:
                text = text[:80] + "..."
            return f"Thinking: {text}"
        elif event_type == "bash":
            cmd = event.get("command", "")
            return f"Running: {cmd[:60]}"
        elif event_type == "result":
            return "Completed"
        elif event_type == "error":
            return f"Error: {event.get('message', 'unknown')}"

        return f"Event: {event_type}"


# ─── Convenience function for runner integration ────────────────

def check_agent_activity(
    working_directory: str,
    process_alive: bool = True,
) -> ActivitySnapshot:
    """Quick check of agent activity. Stateless convenience function."""
    detector = ActivityDetector()
    return detector.detect(working_directory, process_alive)
