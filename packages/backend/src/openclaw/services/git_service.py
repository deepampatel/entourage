"""Git service — worktree management, diffs, and branch-per-task.

Learn: Each task gets its own git worktree and branch. This means:
- Agents work in isolation (no stepping on each other's changes)
- Each task's code changes are on a clean branch
- Diffs are always relative to the default branch (main)
- Merging is a standard git merge

Worktree layout:
  /repo/path/.worktrees/task-42-fix-login/  ← isolated checkout
  Branch: task-42-fix-login

Git operations use asyncio.subprocess (not blocking the event loop).
"""

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openclaw.db.models import Repository, RunTask, Task


@dataclass
class GitResult:
    """Result of a git command."""
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class DiffFile:
    """A file changed in a diff."""
    path: str
    status: str  # A=added, M=modified, D=deleted, R=renamed
    additions: int
    deletions: int


@dataclass
class WorktreeInfo:
    """Info about a task's worktree."""
    path: str
    branch: str
    exists: bool
    repo_path: str
    repo_name: str


async def _run_git(cwd: str, *args: str, timeout: float = 30.0) -> GitResult:
    """Run a git command asynchronously.

    Learn: asyncio.create_subprocess_exec runs git without blocking
    the event loop. Other requests can still be served while git
    runs in the background.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return GitResult(returncode=-1, stdout="", stderr="Git command timed out")

    return GitResult(
        returncode=proc.returncode or 0,
        stdout=stdout.decode().strip(),
        stderr=stderr.decode().strip(),
    )


class GitService:
    """Git operations for task worktrees."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_repo(self, repo_id: uuid.UUID) -> Optional[Repository]:
        result = await self.db.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        return result.scalars().first()

    async def _get_task(self, task_id: int) -> Optional[Task]:
        result = await self.db.execute(
            select(Task).where(Task.id == task_id)
        )
        return result.scalars().first()

    # ─── Worktree Management ─────────────────────────────

    async def create_worktree(
        self,
        task_id: int,
        repo_id: uuid.UUID,
    ) -> WorktreeInfo:
        """Create a git worktree for a task.

        Learn: Git worktrees let you have multiple checkouts of the
        same repo simultaneously. Each task works in its own directory
        on its own branch. No conflicts, no stashing, no switching.

        Steps:
        1. Look up the task (for branch name) and repo (for path)
        2. Create the branch from the default branch
        3. Create the worktree pointing at that branch
        """
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        branch = task.branch
        if not branch:
            raise ValueError(f"Task {task_id} has no branch name")

        worktree_dir = os.path.join(repo.local_path, ".worktrees", branch)

        # Check if worktree already exists
        if os.path.exists(worktree_dir):
            return WorktreeInfo(
                path=worktree_dir,
                branch=branch,
                exists=True,
                repo_path=repo.local_path,
                repo_name=repo.name,
            )

        # Create the branch from default branch
        result = await _run_git(
            repo.local_path,
            "branch", branch, repo.default_branch,
        )
        # Branch might already exist — that's fine
        if not result.ok and "already exists" not in result.stderr:
            raise RuntimeError(f"Failed to create branch: {result.stderr}")

        # Create the worktree
        result = await _run_git(
            repo.local_path,
            "worktree", "add", worktree_dir, branch,
        )
        if not result.ok:
            raise RuntimeError(f"Failed to create worktree: {result.stderr}")

        return WorktreeInfo(
            path=worktree_dir,
            branch=branch,
            exists=True,
            repo_path=repo.local_path,
            repo_name=repo.name,
        )

    async def remove_worktree(
        self,
        task_id: int,
        repo_id: uuid.UUID,
    ) -> bool:
        """Remove a task's worktree (after merge or cancellation)."""
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        worktree_dir = os.path.join(repo.local_path, ".worktrees", task.branch)

        if not os.path.exists(worktree_dir):
            return False

        result = await _run_git(
            repo.local_path,
            "worktree", "remove", worktree_dir, "--force",
        )
        return result.ok

    async def get_worktree_info(
        self,
        task_id: int,
        repo_id: uuid.UUID,
    ) -> WorktreeInfo:
        """Get info about a task's worktree."""
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        worktree_dir = os.path.join(repo.local_path, ".worktrees", task.branch)

        return WorktreeInfo(
            path=worktree_dir,
            branch=task.branch,
            exists=os.path.exists(worktree_dir),
            repo_path=repo.local_path,
            repo_name=repo.name,
        )

    # ─── Diff + File Operations ──────────────────────────

    async def get_diff(
        self,
        task_id: int,
        repo_id: uuid.UUID,
    ) -> str:
        """Get the full diff of a task's branch vs the default branch.

        Learn: This shows exactly what the agent changed. The diff is
        relative to the default branch (main), not the working tree.
        """
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        result = await _run_git(
            repo.local_path,
            "diff", f"{repo.default_branch}...{task.branch}",
        )
        return result.stdout

    async def get_changed_files(
        self,
        task_id: int,
        repo_id: uuid.UUID,
    ) -> list[DiffFile]:
        """List files changed on a task's branch vs the default branch."""
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        # --numstat gives additions/deletions per file
        result = await _run_git(
            repo.local_path,
            "diff", "--numstat", f"{repo.default_branch}...{task.branch}",
        )

        # --name-status gives the status (A/M/D/R)
        status_result = await _run_git(
            repo.local_path,
            "diff", "--name-status", f"{repo.default_branch}...{task.branch}",
        )

        # Parse numstat: "10\t5\tpath/to/file"
        numstat = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                adds = int(parts[0]) if parts[0] != "-" else 0
                dels = int(parts[1]) if parts[1] != "-" else 0
                numstat[parts[2]] = (adds, dels)

        # Parse name-status: "M\tpath/to/file"
        files = []
        for line in status_result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][0]  # First char: A, M, D, R
                path = parts[-1]  # Last part is the path
                adds, dels = numstat.get(path, (0, 0))
                files.append(DiffFile(
                    path=path,
                    status=status,
                    additions=adds,
                    deletions=dels,
                ))

        return files

    async def get_file_content(
        self,
        task_id: int,
        repo_id: uuid.UUID,
        file_path: str,
    ) -> str:
        """Read a file from the task's branch (without needing the worktree)."""
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        result = await _run_git(
            repo.local_path,
            "show", f"{task.branch}:{file_path}",
        )
        if not result.ok:
            raise FileNotFoundError(f"File not found: {file_path} on branch {task.branch}")
        return result.stdout

    async def get_commit_log(
        self,
        task_id: int,
        repo_id: uuid.UUID,
        limit: int = 20,
    ) -> list[dict]:
        """Get commit log for a task's branch."""
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        result = await _run_git(
            repo.local_path,
            "log", f"{repo.default_branch}..{task.branch}",
            f"--max-count={limit}",
            "--format=%H|%an|%ae|%s|%aI",
        )

        commits = []
        for line in result.stdout.splitlines():
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "hash": parts[0],
                    "author_name": parts[1],
                    "author_email": parts[2],
                    "message": parts[3],
                    "date": parts[4],
                })
        return commits

    # ─── Push Operations ─────────────────────────────────

    async def push_branch(
        self,
        task_id: int,
        repo_id: uuid.UUID,
        remote: str = "origin",
        force: bool = False,
    ) -> GitResult:
        """Push a task's branch to the remote.

        Learn: After an agent finishes work, we push the branch so a
        PR can be created. Uses --force-with-lease for safety when
        force-pushing (prevents overwriting others' work).
        """
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        args = ["push", remote, task.branch]
        if force:
            args = ["push", "--force-with-lease", remote, task.branch]

        return await _run_git(repo.local_path, *args, timeout=60.0)

    # ═══════════════════════════════════════════════════════
    # Branch-based methods (work with RunTask, no Task dependency)
    # ═══════════════════════════════════════════════════════

    async def create_branch(
        self,
        branch_name: str,
        base_branch: str,
        repo_id: uuid.UUID,
    ) -> GitResult:
        """Create a new git branch from base. Idempotent — ok if exists."""
        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        result = await _run_git(
            repo.local_path,
            "branch", branch_name, base_branch,
        )
        if not result.ok and "already exists" not in result.stderr:
            raise RuntimeError(f"Failed to create branch {branch_name}: {result.stderr}")
        return result

    async def create_run_worktree(
        self,
        run_task_id: int,
        repo_id: uuid.UUID,
        base_branch: str,
    ) -> WorktreeInfo:
        """Create a worktree for a RunTask, branching from the run's feature branch.

        Unlike create_worktree (which uses Task model), this reads
        RunTask.branch_name and branches from the feature branch,
        not from main.
        """
        result = await self.db.execute(
            select(RunTask).where(RunTask.id == run_task_id)
        )
        run_task = result.scalars().first()
        if not run_task:
            raise ValueError(f"RunTask {run_task_id} not found")

        branch = run_task.branch_name
        if not branch:
            raise ValueError(f"RunTask {run_task_id} has no branch_name")

        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        worktree_dir = os.path.join(repo.local_path, ".worktrees", branch.replace("/", "-"))

        if os.path.exists(worktree_dir):
            return WorktreeInfo(
                path=worktree_dir,
                branch=branch,
                exists=True,
                repo_path=repo.local_path,
                repo_name=repo.name,
            )

        # Create branch from feature branch (not main)
        await self.create_branch(branch, base_branch, repo_id)

        # Create worktree
        wt_result = await _run_git(
            repo.local_path,
            "worktree", "add", worktree_dir, branch,
        )
        if not wt_result.ok:
            raise RuntimeError(f"Failed to create worktree: {wt_result.stderr}")

        return WorktreeInfo(
            path=worktree_dir,
            branch=branch,
            exists=True,
            repo_path=repo.local_path,
            repo_name=repo.name,
        )

    async def merge_branch(
        self,
        source_branch: str,
        target_branch: str,
        repo_id: uuid.UUID,
        strategy: str = "merge",
    ) -> GitResult:
        """Merge source branch into target. Returns GitResult with conflict info if failed."""
        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        # Checkout target branch
        checkout = await _run_git(repo.local_path, "checkout", target_branch)
        if not checkout.ok:
            return checkout

        if strategy == "squash":
            result = await _run_git(
                repo.local_path,
                "merge", "--squash", source_branch,
            )
            if result.ok:
                # Squash needs an explicit commit
                await _run_git(
                    repo.local_path,
                    "commit", "-m", f"Squash merge {source_branch} into {target_branch}",
                )
        elif strategy == "rebase":
            result = await _run_git(
                repo.local_path,
                "rebase", source_branch,
            )
        else:
            result = await _run_git(
                repo.local_path,
                "merge", "--no-ff", source_branch,
                "-m", f"Merge {source_branch} into {target_branch}",
            )

        if not result.ok:
            # Abort the failed merge to leave repo clean
            await _run_git(repo.local_path, "merge", "--abort")
            await _run_git(repo.local_path, "rebase", "--abort")

        return result

    async def get_branch_diff(
        self,
        branch: str,
        base_branch: str,
        repo_id: uuid.UUID,
    ) -> str:
        """Get unified diff between two branches."""
        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        result = await _run_git(
            repo.local_path,
            "diff", f"{base_branch}...{branch}",
        )
        return result.stdout

    async def get_branch_changed_files(
        self,
        branch: str,
        base_branch: str,
        repo_id: uuid.UUID,
    ) -> list[DiffFile]:
        """List files changed between two branches."""
        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        numstat = await _run_git(
            repo.local_path,
            "diff", "--numstat", f"{base_branch}...{branch}",
        )
        name_status = await _run_git(
            repo.local_path,
            "diff", "--name-status", f"{base_branch}...{branch}",
        )

        stats = {}
        for line in numstat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                adds = int(parts[0]) if parts[0] != "-" else 0
                dels = int(parts[1]) if parts[1] != "-" else 0
                stats[parts[2]] = (adds, dels)

        files = []
        for line in name_status.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][0]
                path = parts[-1]
                adds, dels = stats.get(path, (0, 0))
                files.append(DiffFile(path=path, status=status, additions=adds, deletions=dels))

        return files

    async def push_branch_by_name(
        self,
        branch: str,
        repo_id: uuid.UUID,
        remote: str = "origin",
        force: bool = False,
    ) -> GitResult:
        """Push a branch to remote by name (no Task lookup)."""
        repo = await self._get_repo(repo_id)
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        args = ["push", remote, branch]
        if force:
            args = ["push", "--force-with-lease", remote, branch]

        return await _run_git(repo.local_path, *args, timeout=60.0)

    async def remove_run_worktree(
        self,
        branch_name: str,
        repo_id: uuid.UUID,
    ) -> bool:
        """Remove a worktree by branch name."""
        repo = await self._get_repo(repo_id)
        if not repo:
            return False

        worktree_dir = os.path.join(repo.local_path, ".worktrees", branch_name.replace("/", "-"))
        if not os.path.exists(worktree_dir):
            return False

        result = await _run_git(repo.local_path, "worktree", "remove", worktree_dir, "--force")
        return result.ok

    async def validate_repo(self, local_path: str) -> dict:
        """Validate a path is a git repo. Returns health info."""
        info: dict = {
            "valid": False,
            "default_branch": None,
            "current_branch": None,
            "is_dirty": False,
            "remote_url": None,
            "error": None,
        }

        if not os.path.isdir(local_path):
            info["error"] = f"Path does not exist: {local_path}"
            return info

        # Check if git repo
        result = await _run_git(local_path, "rev-parse", "--is-inside-work-tree")
        if not result.ok:
            info["error"] = "Not a git repository"
            return info

        info["valid"] = True

        # Current branch
        result = await _run_git(local_path, "symbolic-ref", "--short", "HEAD")
        if result.ok:
            info["current_branch"] = result.stdout

        # Default branch (try origin/HEAD, fall back to current)
        result = await _run_git(local_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if result.ok:
            info["default_branch"] = result.stdout.replace("origin/", "")
        else:
            info["default_branch"] = info["current_branch"] or "main"

        # Dirty state
        result = await _run_git(local_path, "status", "--porcelain")
        info["is_dirty"] = bool(result.stdout.strip())

        # Remote URL
        result = await _run_git(local_path, "remote", "get-url", "origin")
        if result.ok:
            info["remote_url"] = result.stdout

        return info
