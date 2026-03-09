"""Tests for ContextRotation service."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.services.context_rotation import ContextRotation


@pytest.fixture
def worktree(tmp_path):
    """Create a worktree with .openclaw directory."""
    wt = tmp_path / "worktree"
    (wt / ".openclaw").mkdir(parents=True)
    return str(wt)


class TestCheckAndRotate:
    @pytest.mark.asyncio
    async def test_no_rotation_under_threshold(self, worktree):
        """No rotation when content is small."""
        # Write a small reflections file
        reflections = Path(worktree) / ".openclaw" / "reflections.md"
        reflections.write_text("Small content")

        rotation = ContextRotation(max_tokens=100_000)
        result = await rotation.check_and_rotate(worktree)

        assert result is False
        assert reflections.read_text() == "Small content"

    @pytest.mark.asyncio
    async def test_no_rotation_when_dir_missing(self, tmp_path):
        """No rotation when .openclaw dir doesn't exist."""
        rotation = ContextRotation(max_tokens=100)
        result = await rotation.check_and_rotate(str(tmp_path / "nonexistent"))

        assert result is False

    @pytest.mark.asyncio
    async def test_rotation_summarizes(self, worktree):
        """When over threshold, files are summarized."""
        reflections = Path(worktree) / ".openclaw" / "reflections.md"
        # Write enough content to exceed a very low threshold
        large_content = "Lesson learned: " * 500
        reflections.write_text(large_content)

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summarized: key lessons about patterns")]
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        rotation = ContextRotation(
            max_tokens=10,  # Very low threshold to trigger rotation
            anthropic_client=mock_client,
        )
        result = await rotation.check_and_rotate(worktree)

        assert result is True
        new_content = reflections.read_text()
        assert "Summarized Context" in new_content
        assert "Summarized: key lessons" in new_content

    @pytest.mark.asyncio
    async def test_skips_small_files(self, worktree):
        """Files under 500 chars are not summarized."""
        small_file = Path(worktree) / ".openclaw" / "reflections.md"
        small_file.write_text("Short")

        # Force rotation by using explicit token estimate
        rotation = ContextRotation(max_tokens=1)
        result = await rotation.check_and_rotate(worktree, current_token_estimate=100)

        # Returns True because threshold was exceeded, but file stays small
        assert result is True
        assert small_file.read_text() == "Short"

    @pytest.mark.asyncio
    async def test_explicit_token_estimate(self, worktree):
        """Pre-computed token estimate is used when provided."""
        reflections = Path(worktree) / ".openclaw" / "reflections.md"
        reflections.write_text("Some content")

        rotation = ContextRotation(max_tokens=50)

        # Under threshold
        result = await rotation.check_and_rotate(worktree, current_token_estimate=30)
        assert result is False

    @pytest.mark.asyncio
    async def test_fallback_without_anthropic(self, worktree):
        """Truncates when anthropic client can't be imported."""
        reflections = Path(worktree) / ".openclaw" / "reflections.md"
        large_content = "Important lesson: " * 500
        reflections.write_text(large_content)

        rotation = ContextRotation(max_tokens=10)
        # Patch the import to fail
        with patch.dict("sys.modules", {"anthropic": None}):
            rotation._client = None
            result = await rotation.check_and_rotate(worktree)

        assert result is True
        new_content = reflections.read_text()
        assert "Summarized Context" in new_content
