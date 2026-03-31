"""Tmux runtime — runs agents in tmux sessions for live observation + crash survival.

Why tmux over bare subprocess:
1. LIVE OBSERVATION: `tmux attach -t eo-task-42` — watch the agent work in real-time
2. CRASH SURVIVAL: tmux sessions persist if the backend process dies
3. NO STDOUT LIMITS: read output via capture-pane, not pipe buffers
4. MESSAGE DELIVERY: send prompts via load-buffer + paste-buffer (no 200-char limit)

Inspired by ComposioHQ/agent-orchestrator's runtime-tmux plugin.
"""

import asyncio
import logging
import os
import shutil
import tempfile
import time

from openclaw.agent.runtime.base import Runtime, RuntimeConfig, RuntimeSession

logger = logging.getLogger("openclaw.agent.runtime.tmux")

# Prefix for all entourage tmux sessions (easy to list/cleanup)
SESSION_PREFIX = "eo-"


class TmuxRuntime(Runtime):
    """Tmux-based agent runtime."""

    @property
    def name(self) -> str:
        return "tmux"

    def validate(self) -> tuple[bool, str]:
        """Check that tmux is installed."""
        if shutil.which("tmux"):
            return True, "tmux found"
        return False, "tmux not found. Install with: brew install tmux"

    async def create(self, config: RuntimeConfig) -> RuntimeSession:
        """Spawn agent in a new detached tmux session.

        Flow:
        1. Create detached tmux session with env vars
        2. Send the command to execute inside it
        3. Return session handle with attach command
        """
        session_name = f"{SESSION_PREFIX}{config.session_id}"

        # Kill any existing session with this name (stale from crash)
        await self._run_tmux("kill-session", "-t", session_name, ignore_errors=True)

        # Build env exports as prefix (for the shell command)
        env_prefix_parts = []
        for key, value in config.env.items():
            if "\n" in value:
                continue
            safe_val = value.replace("'", "'\\''")
            env_prefix_parts.append(f"{key}='{safe_val}'")
        env_prefix = " ".join(env_prefix_parts)

        # Build command string
        if len(config.command) == 1 and os.path.isfile(config.command[0]):
            # Single executable (launcher script) — run directly
            cmd_str = config.command[0]
        else:
            quoted_parts = []
            for part in config.command:
                if any(c in part for c in " *?[]{}$\"'\\|&;<>()!#~"):
                    safe = part.replace("'", "'\\''")
                    quoted_parts.append(f"'{safe}'")
                else:
                    quoted_parts.append(part)
            cmd_str = " ".join(quoted_parts)

        # Build full shell command with env vars.
        # Append "; exit" so the shell exits when the agent finishes,
        # making pane_dead=1 and is_alive() returns False.
        full_cmd = f"{env_prefix + ' ' if env_prefix else ''}{cmd_str}; exit"

        # Create detached session with remain-on-exit so we can
        # still capture-pane output after the process exits.
        await self._run_tmux(
            "new-session",
            "-d",                    # Detached
            "-s", session_name,      # Session name
            "-c", config.cwd,        # Working directory
            "-x", "220",             # Wide terminal
            "-y", "50",              # Tall terminal
        )

        await self._run_tmux(
            "set-option", "-t", session_name,
            "remain-on-exit", "on",
        )

        # Send the command
        await self._send_keys(session_name, full_cmd)

        logger.info(
            "Created tmux session '%s' running: %s",
            session_name, cmd_str[:100],
        )

        return RuntimeSession(
            session_id=session_name,
            runtime_type="tmux",
            cwd=config.cwd,
            started_at=time.time(),
            env=config.env,
            attach_command=f"tmux attach -t {session_name}",
        )

    async def send_message(self, session: RuntimeSession, message: str) -> bool:
        """Send text to the agent via tmux load-buffer + paste-buffer.

        Why not send-keys? tmux send-keys truncates at ~200 chars.
        load-buffer + paste-buffer handles arbitrary length text.
        """
        try:
            # Write message to temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="eo-msg-", delete=False
            ) as f:
                f.write(message)
                tmp_path = f.name

            try:
                # Clear any existing input first
                await self._run_tmux(
                    "send-keys", "-t", session.session_id, "C-u"
                )
                await asyncio.sleep(0.1)

                # Load the message into a tmux buffer
                await self._run_tmux(
                    "load-buffer", "-b", "eo-prompt", tmp_path
                )

                # Paste it into the session
                await self._run_tmux(
                    "paste-buffer", "-b", "eo-prompt",
                    "-t", session.session_id,
                    "-d",  # Delete buffer after paste
                )

                # Send Enter to submit
                await asyncio.sleep(0.3)
                await self._run_tmux(
                    "send-keys", "-t", session.session_id, "Enter"
                )

                logger.debug(
                    "Sent %d-char message to session '%s'",
                    len(message), session.session_id,
                )
                return True

            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(
                "Failed to send message to '%s': %s",
                session.session_id, e,
            )
            return False

    async def read_output(self, session: RuntimeSession, lines: int = 500) -> str:
        """Capture recent terminal output via tmux capture-pane."""
        try:
            result = await self._run_tmux(
                "capture-pane",
                "-t", session.session_id,
                "-p",                    # Print to stdout
                "-S", f"-{lines}",       # Start N lines back from bottom
            )
            return result.strip()
        except Exception as e:
            logger.debug("Failed to read output from '%s': %s", session.session_id, e)
            return ""

    async def is_alive(self, session: RuntimeSession) -> bool:
        """Check if the tmux session still exists and has a running process."""
        try:
            # Check session exists
            result = await self._run_tmux(
                "list-panes",
                "-t", session.session_id,
                "-F", "#{pane_pid} #{pane_dead}",
            )

            for line in result.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    _pid, dead = parts[0], parts[1]
                    if dead == "0":
                        return True
                elif len(parts) == 1:
                    # No dead flag means it's alive
                    return True

            return False

        except Exception:
            return False

    async def kill(self, session: RuntimeSession) -> None:
        """Kill the tmux session and all processes in it."""
        try:
            # First try sending Ctrl-C to gracefully stop
            await self._run_tmux(
                "send-keys", "-t", session.session_id, "C-c"
            )
            await asyncio.sleep(1)

            # Then kill the session
            await self._run_tmux(
                "kill-session", "-t", session.session_id,
                ignore_errors=True,
            )
            logger.info("Killed tmux session '%s'", session.session_id)

        except Exception as e:
            logger.debug("Error killing session '%s': %s", session.session_id, e)

    # ─── List/cleanup helpers ─────────────────────────────────

    async def list_sessions(self) -> list[str]:
        """List all entourage tmux sessions."""
        try:
            result = await self._run_tmux(
                "list-sessions", "-F", "#{session_name}",
                ignore_errors=True,
            )
            return [
                name.strip() for name in result.strip().split("\n")
                if name.strip().startswith(SESSION_PREFIX)
            ]
        except Exception:
            return []

    async def cleanup_dead_sessions(self) -> int:
        """Kill entourage sessions where the pane process has exited."""
        cleaned = 0
        sessions = await self.list_sessions()
        for session_name in sessions:
            handle = RuntimeSession(
                session_id=session_name,
                runtime_type="tmux",
            )
            if not await self.is_alive(handle):
                await self.kill(handle)
                cleaned += 1
        if cleaned:
            logger.info("Cleaned up %d dead tmux sessions", cleaned)
        return cleaned

    # ─── Internal helpers ─────────────────────────────────────

    async def _send_keys(self, session_name: str, text: str) -> None:
        """Send text via send-keys (for short strings like env exports).

        For long text (prompts), use send_message() which uses load-buffer.
        """
        # Use load-buffer for anything over 150 chars to avoid truncation
        if len(text) > 150:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write(text)
                tmp_path = f.name
            try:
                await self._run_tmux("load-buffer", "-b", "eo-keys", tmp_path)
                await self._run_tmux(
                    "paste-buffer", "-b", "eo-keys",
                    "-t", session_name, "-d",
                )
            finally:
                os.unlink(tmp_path)
        else:
            await self._run_tmux(
                "send-keys", "-t", session_name, text,
            )
        # Send Enter
        await self._run_tmux("send-keys", "-t", session_name, "Enter")

    async def _run_tmux(
        self, *args: str, ignore_errors: bool = False
    ) -> str:
        """Execute a tmux command and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            "tmux", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0 and not ignore_errors:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"tmux {args[0]} failed: {err_msg}")

        return stdout.decode("utf-8", errors="replace")
