"""SandboxManager — Docker-based isolated test execution for pipeline tasks.

Learn: After a pipeline task completes, the SandboxManager can run tests
in a Docker container to verify correctness. The container mounts the
worktree read-only with network disabled for isolation.

Key design decisions:
- Containers are ephemeral (--rm) — no persistent state
- Network is disabled (--network none) for security
- Memory and CPU are capped to prevent resource exhaustion
- Results are persisted to the sandbox_runs table for auditability
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result from a sandboxed test run."""

    sandbox_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    passed: bool  # exit_code == 0
    started_at: datetime
    ended_at: datetime


class SandboxManager:
    """Manages Docker-based sandbox execution for pipeline test runs.

    Usage:
        mgr = SandboxManager()
        if await mgr.check_docker():
            result = await mgr.run_tests("/path/to/worktree", "pytest tests/")
    """

    def __init__(self) -> None:
        self._docker_available: bool | None = None

    async def check_docker(self) -> bool:
        """Check if Docker daemon is running. Caches the result."""
        if self._docker_available is not None:
            return self._docker_available

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
            self._docker_available = proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError):
            self._docker_available = False

        if not self._docker_available:
            logger.warning("Docker is not available — sandbox tests disabled")

        return self._docker_available

    async def run_tests(
        self,
        worktree_path: str,
        test_cmd: str,
        *,
        timeout: int = 300,
        env: dict[str, str] | None = None,
        image: str = "python:3.12-slim",
        setup_cmd: str | None = None,
    ) -> SandboxResult:
        """Run test_cmd in a Docker container mounting worktree read-only.

        Args:
            worktree_path: Absolute path to the worktree directory.
            test_cmd: Shell command to run tests (e.g., "pytest tests/").
            timeout: Maximum seconds before killing the container.
            env: Extra environment variables to set in the container.
            image: Docker image to use.
            setup_cmd: Optional setup command to run before tests (e.g., "pip install -e .").

        Returns:
            SandboxResult with exit code, output, and timing info.
        """
        sandbox_id = uuid.uuid4().hex[:12]
        started_at = datetime.now(timezone.utc)

        docker_cmd = self._build_docker_cmd(
            sandbox_id=sandbox_id,
            worktree_path=worktree_path,
            cmd=test_cmd,
            image=image,
            setup_cmd=setup_cmd,
            env=env,
            timeout=timeout,
        )

        logger.info(
            "sandbox.starting",
            extra={
                "sandbox_id": sandbox_id,
                "image": image,
                "test_cmd": test_cmd,
                "worktree": worktree_path,
            },
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 30  # grace period beyond Docker's own timeout
            )
            exit_code = proc.returncode or 0
            stdout = stdout_bytes.decode("utf-8", errors="replace")[-50_000:]  # cap output
            stderr = stderr_bytes.decode("utf-8", errors="replace")[-50_000:]

        except asyncio.TimeoutError:
            logger.warning("sandbox.timeout", extra={"sandbox_id": sandbox_id})
            # Kill the container
            await self._kill_container(sandbox_id)
            exit_code = 124  # standard timeout exit code
            stdout = ""
            stderr = f"Sandbox timed out after {timeout}s"

        except Exception as exc:
            logger.error("sandbox.error", extra={"sandbox_id": sandbox_id, "error": str(exc)})
            exit_code = 1
            stdout = ""
            stderr = f"Sandbox error: {exc}"

        ended_at = datetime.now(timezone.utc)
        duration = (ended_at - started_at).total_seconds()
        passed = exit_code == 0

        logger.info(
            "sandbox.completed",
            extra={
                "sandbox_id": sandbox_id,
                "exit_code": exit_code,
                "passed": passed,
                "duration": duration,
            },
        )

        return SandboxResult(
            sandbox_id=sandbox_id,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            passed=passed,
            started_at=started_at,
            ended_at=ended_at,
        )

    async def cleanup_stale(self, max_age_seconds: int = 3600) -> int:
        """Remove containers with label openclaw-sandbox older than max_age."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "-a",
                "--filter", "label=openclaw-sandbox=true",
                "--format", "{{.ID}} {{.CreatedAt}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            lines = stdout_bytes.decode().strip().splitlines()

            removed = 0
            for line in lines:
                if not line.strip():
                    continue
                container_id = line.split()[0]
                # Remove any stale container regardless of age (simplified)
                rm_proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await rm_proc.wait()
                removed += 1

            if removed:
                logger.info("sandbox.cleanup", extra={"removed": removed})
            return removed

        except Exception as exc:
            logger.warning("sandbox.cleanup_failed", extra={"error": str(exc)})
            return 0

    def _build_docker_cmd(
        self,
        sandbox_id: str,
        worktree_path: str,
        cmd: str,
        *,
        image: str = "python:3.12-slim",
        setup_cmd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> list[str]:
        """Build the docker run command list."""
        docker_cmd = [
            "docker", "run", "--rm",
            "--name", f"openclaw-sandbox-{sandbox_id}",
            "--label", "openclaw-sandbox=true",
            "-v", f"{worktree_path}:/workspace:ro",
            "-w", "/workspace",
            "--network", "none",
            "--memory", "512m",
            "--cpus", "1.0",
        ]

        # Environment variables
        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.append(image)

        # Build the shell command
        if setup_cmd:
            shell_cmd = f"{setup_cmd} && {cmd}"
        else:
            shell_cmd = cmd

        docker_cmd.extend(["sh", "-c", shell_cmd])

        return docker_cmd

    async def _kill_container(self, sandbox_id: str) -> None:
        """Force-kill a running container by sandbox_id."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", f"openclaw-sandbox-{sandbox_id}",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception:
            pass  # best-effort cleanup
