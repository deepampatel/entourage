"""Tests for ReviewDeduplicator — SHA-256 fingerprinting of review comments."""

import pytest

from openclaw.services.review_dedup import ReviewDeduplicator


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
async def org(client):
    resp = await client.post(
        "/api/v1/orgs", json={"name": "Dedup Org", "slug": "dedup-org"}
    )
    return resp.json()


@pytest.fixture
async def team(client, org):
    resp = await client.post(
        f"/api/v1/orgs/{org['id']}/teams",
        json={"name": "Dedup Team", "slug": "dedup-team"},
    )
    return resp.json()


@pytest.fixture
async def task(client, team):
    resp = await client.post(
        f"/api/v1/teams/{team['id']}/tasks",
        json={"title": "Review target", "description": "Code to review"},
    )
    return resp.json()


@pytest.fixture
async def review(client, task):
    resp = await client.post(
        f"/api/v1/tasks/{task['id']}/reviews",
        json={"reviewer_id": "00000000-0000-0000-0000-000000000001", "reviewer_type": "user"},
    )
    return resp.json()


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestFingerprint:
    """Test the static fingerprint method."""

    def test_same_content_same_fingerprint(self):
        """Identical comments produce the same fingerprint."""
        from unittest.mock import MagicMock

        c1 = MagicMock()
        c1.file_path = "src/main.py"
        c1.line_number = 42
        c1.content = "Missing error handling here"

        c2 = MagicMock()
        c2.file_path = "src/main.py"
        c2.line_number = 42
        c2.content = "Missing error handling here"

        fp1 = ReviewDeduplicator.fingerprint(c1)
        fp2 = ReviewDeduplicator.fingerprint(c2)
        assert fp1 == fp2

    def test_different_content_different_fingerprint(self):
        from unittest.mock import MagicMock

        c1 = MagicMock()
        c1.file_path = "src/main.py"
        c1.line_number = 42
        c1.content = "Missing error handling"

        c2 = MagicMock()
        c2.file_path = "src/main.py"
        c2.line_number = 42
        c2.content = "Add type annotations"

        fp1 = ReviewDeduplicator.fingerprint(c1)
        fp2 = ReviewDeduplicator.fingerprint(c2)
        assert fp1 != fp2

    def test_case_insensitive(self):
        """Fingerprinting is case-insensitive."""
        from unittest.mock import MagicMock

        c1 = MagicMock()
        c1.file_path = "src/main.py"
        c1.line_number = 42
        c1.content = "Missing Error Handling"

        c2 = MagicMock()
        c2.file_path = "src/main.py"
        c2.line_number = 42
        c2.content = "missing error handling"

        assert ReviewDeduplicator.fingerprint(c1) == ReviewDeduplicator.fingerprint(c2)

    def test_whitespace_stripped(self):
        from unittest.mock import MagicMock

        c1 = MagicMock()
        c1.file_path = "src/main.py"
        c1.line_number = 42
        c1.content = "  Fix this  "

        c2 = MagicMock()
        c2.file_path = "src/main.py"
        c2.line_number = 42
        c2.content = "Fix this"

        assert ReviewDeduplicator.fingerprint(c1) == ReviewDeduplicator.fingerprint(c2)

    def test_different_line_different_fingerprint(self):
        """Same content on different lines produces different fingerprints."""
        from unittest.mock import MagicMock

        c1 = MagicMock()
        c1.file_path = "src/main.py"
        c1.line_number = 42
        c1.content = "Fix this"

        c2 = MagicMock()
        c2.file_path = "src/main.py"
        c2.line_number = 99
        c2.content = "Fix this"

        assert ReviewDeduplicator.fingerprint(c1) != ReviewDeduplicator.fingerprint(c2)


class TestFilterNewComments:
    """Test comment deduplication via filter_new_comments."""

    async def test_all_new_comments_pass_through(self, db_session):
        """When no prior comments exist, all comments are new."""
        from unittest.mock import MagicMock

        dedup = ReviewDeduplicator(db_session)

        comments = []
        for i in range(3):
            c = MagicMock()
            c.id = i + 1
            c.file_path = f"src/file{i}.py"
            c.line_number = 10 + i
            c.content = f"Issue #{i}"
            comments.append(c)

        # Task ID with no prior comments
        result = await dedup.filter_new_comments(task_id=99999, comments=comments)
        assert len(result) == 3

    async def test_duplicate_comments_filtered(self, db_session):
        """Second call with same comments filters them out."""
        from unittest.mock import MagicMock

        dedup = ReviewDeduplicator(db_session)

        c1 = MagicMock()
        c1.id = 1
        c1.file_path = "src/main.py"
        c1.line_number = 42
        c1.content = "Missing error handling"

        # First call: new
        result = await dedup.filter_new_comments(task_id=99999, comments=[c1])
        assert len(result) == 1

        # Second call: duplicate
        c2 = MagicMock()
        c2.id = 2
        c2.file_path = "src/main.py"
        c2.line_number = 42
        c2.content = "Missing error handling"

        result = await dedup.filter_new_comments(task_id=99999, comments=[c2])
        assert len(result) == 0

    async def test_clear_cache_resets(self, db_session):
        """clear_cache allows previously seen comments through again."""
        from unittest.mock import MagicMock

        dedup = ReviewDeduplicator(db_session)

        c = MagicMock()
        c.id = 1
        c.file_path = "src/main.py"
        c.line_number = 42
        c.content = "Fix this"

        await dedup.filter_new_comments(task_id=99999, comments=[c])

        # Clear and try again
        dedup.clear_cache(task_id=99999)
        result = await dedup.filter_new_comments(task_id=99999, comments=[c])
        assert len(result) == 1


class TestMarkDispatched:
    """Test explicit dispatch marking."""

    def test_mark_dispatched_adds_fingerprints(self):
        from unittest.mock import MagicMock

        dedup = ReviewDeduplicator(MagicMock())

        c = MagicMock()
        c.file_path = "src/main.py"
        c.line_number = 42
        c.content = "Fix this"

        dedup.mark_dispatched(task_id=1, comments=[c])

        assert 1 in dedup._dispatched
        assert len(dedup._dispatched[1]) == 1
