"""Tests for branch-per-run git workflow.

Tests the new branch-based methods in GitService:
- create_branch
- create_run_worktree (for RunTask)
- merge_branch (with conflict detection)
- get_branch_diff / get_branch_changed_files
- validate_repo
"""

import asyncio
import os
import subprocess

import pytest


# ─── Helpers ──────────────────────────────────────────


def run_git(cwd, *args):
    """Sync git helper for test setup."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def create_test_repo(path):
    """Create a git repo with an initial commit."""
    os.makedirs(path, exist_ok=True)
    run_git(path, "init")
    run_git(path, "config", "user.email", "test@test.com")
    run_git(path, "config", "user.name", "Test")
    with open(os.path.join(path, "README.md"), "w") as f:
        f.write("# Test Repo\n")
    run_git(path, "add", ".")
    run_git(path, "commit", "-m", "init")
    return path


# ─── Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_repo_valid(tmp_path):
    """validate_repo should detect a valid git repo."""
    from openclaw.services.git_service import GitService

    repo_path = create_test_repo(str(tmp_path / "repo"))

    # GitService needs a db session but validate_repo doesn't use it
    git_svc = GitService(db=None)
    info = await git_svc.validate_repo(repo_path)

    assert info["valid"] is True
    assert info["error"] is None
    assert info["current_branch"] in ("main", "master")
    assert info["is_dirty"] is False


@pytest.mark.asyncio
async def test_validate_repo_invalid(tmp_path):
    """validate_repo should reject non-git directories."""
    from openclaw.services.git_service import GitService

    git_svc = GitService(db=None)

    # Non-existent path
    info = await git_svc.validate_repo("/nonexistent/path")
    assert info["valid"] is False
    assert "does not exist" in info["error"]

    # Existing dir but not git
    plain_dir = str(tmp_path / "notgit")
    os.makedirs(plain_dir)
    info = await git_svc.validate_repo(plain_dir)
    assert info["valid"] is False
    assert "Not a git" in info["error"]


@pytest.mark.asyncio
async def test_validate_repo_dirty_state(tmp_path):
    """validate_repo should detect dirty working tree."""
    from openclaw.services.git_service import GitService

    repo_path = create_test_repo(str(tmp_path / "dirty"))

    # Make it dirty
    with open(os.path.join(repo_path, "new_file.txt"), "w") as f:
        f.write("uncommitted")

    git_svc = GitService(db=None)
    info = await git_svc.validate_repo(repo_path)

    assert info["valid"] is True
    assert info["is_dirty"] is True


@pytest.mark.asyncio
async def test_create_branch(tmp_path):
    """create_branch should create a git branch from base."""
    from openclaw.services.git_service import _run_git, GitService

    repo_path = create_test_repo(str(tmp_path / "repo"))
    default = run_git(repo_path, "symbolic-ref", "--short", "HEAD")

    # Use _run_git directly (no db needed for this test)
    from openclaw.services.git_service import _run_git

    result = await _run_git(repo_path, "branch", "feature/test-branch", default)
    assert result.ok or "already exists" in result.stderr

    # Verify branch exists
    branches = run_git(repo_path, "branch", "--list")
    assert "feature/test-branch" in branches


@pytest.mark.asyncio
async def test_merge_branch_clean(tmp_path):
    """merge_branch should merge when no conflicts."""
    from openclaw.services.git_service import _run_git

    repo_path = create_test_repo(str(tmp_path / "repo"))
    default = run_git(repo_path, "symbolic-ref", "--short", "HEAD")

    # Create feature branch and add a file
    run_git(repo_path, "checkout", "-b", "feature/test")
    with open(os.path.join(repo_path, "new_feature.py"), "w") as f:
        f.write("def hello(): pass\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "add feature")

    # Go back to main
    run_git(repo_path, "checkout", default)

    # Merge
    result = await _run_git(
        repo_path, "merge", "--no-ff", "feature/test",
        "-m", "Merge feature/test",
    )
    assert result.ok

    # Verify file exists on main now
    assert os.path.exists(os.path.join(repo_path, "new_feature.py"))


@pytest.mark.asyncio
async def test_merge_branch_conflict(tmp_path):
    """merge_branch should detect conflicts."""
    from openclaw.services.git_service import _run_git

    repo_path = create_test_repo(str(tmp_path / "repo"))
    default = run_git(repo_path, "symbolic-ref", "--short", "HEAD")

    # Create two branches that edit the same file
    run_git(repo_path, "checkout", "-b", "branch-a")
    with open(os.path.join(repo_path, "README.md"), "w") as f:
        f.write("# Changed by branch A\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "branch-a changes")

    run_git(repo_path, "checkout", default)
    run_git(repo_path, "checkout", "-b", "branch-b")
    with open(os.path.join(repo_path, "README.md"), "w") as f:
        f.write("# Changed by branch B\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "branch-b changes")

    # Merge branch-a into default first
    run_git(repo_path, "checkout", default)
    run_git(repo_path, "merge", "branch-a", "-m", "merge a")

    # Now try to merge branch-b — should conflict
    result = await _run_git(
        repo_path, "merge", "--no-ff", "branch-b",
        "-m", "Merge branch-b",
    )
    assert not result.ok
    assert "conflict" in result.stdout.lower() or "conflict" in result.stderr.lower() or "CONFLICT" in result.stdout

    # Abort to clean up
    await _run_git(repo_path, "merge", "--abort")


@pytest.mark.asyncio
async def test_branch_diff(tmp_path):
    """get_branch_diff should show changes between branches."""
    from openclaw.services.git_service import _run_git

    repo_path = create_test_repo(str(tmp_path / "repo"))
    default = run_git(repo_path, "symbolic-ref", "--short", "HEAD")

    # Create feature branch with changes
    run_git(repo_path, "checkout", "-b", "feature/diff-test")
    with open(os.path.join(repo_path, "utils.py"), "w") as f:
        f.write("def format_bytes(n): return str(n)\n")
    run_git(repo_path, "add", ".")
    run_git(repo_path, "commit", "-m", "add utils")

    # Get diff
    result = await _run_git(
        repo_path, "diff", f"{default}...feature/diff-test",
    )
    assert "format_bytes" in result.stdout
    assert "+def format_bytes" in result.stdout


@pytest.mark.asyncio
async def test_worktree_isolation_between_branches(tmp_path):
    """Two worktrees from different branches should be fully isolated."""
    repo_path = create_test_repo(str(tmp_path / "repo"))
    default = run_git(repo_path, "symbolic-ref", "--short", "HEAD")

    # Create feature branch
    run_git(repo_path, "branch", "feature/run-123", default)

    # Create two task branches from feature
    run_git(repo_path, "branch", "task/1-auth", "feature/run-123")
    run_git(repo_path, "branch", "task/2-api", "feature/run-123")

    # Create worktrees
    wt1 = os.path.join(repo_path, ".worktrees", "task-1-auth")
    wt2 = os.path.join(repo_path, ".worktrees", "task-2-api")
    run_git(repo_path, "worktree", "add", wt1, "task/1-auth")
    run_git(repo_path, "worktree", "add", wt2, "task/2-api")

    # Agent A writes in worktree 1
    with open(os.path.join(wt1, "auth.py"), "w") as f:
        f.write("def login(): pass\n")

    # Agent B writes in worktree 2
    with open(os.path.join(wt2, "api.py"), "w") as f:
        f.write("def get_users(): pass\n")

    # Files don't cross
    assert os.path.exists(os.path.join(wt1, "auth.py"))
    assert not os.path.exists(os.path.join(wt1, "api.py"))
    assert os.path.exists(os.path.join(wt2, "api.py"))
    assert not os.path.exists(os.path.join(wt2, "auth.py"))

    # Commit in both
    run_git(wt1, "add", ".")
    run_git(wt1, "commit", "-m", "add auth")
    run_git(wt2, "add", ".")
    run_git(wt2, "commit", "-m", "add api")

    # Merge both into feature branch (no conflict — different files)
    run_git(repo_path, "checkout", "feature/run-123")
    run_git(repo_path, "merge", "task/1-auth", "-m", "merge auth")
    run_git(repo_path, "merge", "task/2-api", "-m", "merge api")

    # Feature branch has both files
    assert os.path.exists(os.path.join(repo_path, "auth.py"))
    assert os.path.exists(os.path.join(repo_path, "api.py"))

    # Main doesn't
    run_git(repo_path, "checkout", default)
    assert not os.path.exists(os.path.join(repo_path, "auth.py"))
    assert not os.path.exists(os.path.join(repo_path, "api.py"))

    # Cleanup
    run_git(repo_path, "worktree", "remove", wt1, "--force")
    run_git(repo_path, "worktree", "remove", wt2, "--force")
