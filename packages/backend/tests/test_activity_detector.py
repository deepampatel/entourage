"""Tests for ActivityDetector — reads Claude Code session files for real-time status."""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from openclaw.services.activity_detector import (
    ActivityDetector,
    AgentState,
    _ACTIVE_THRESHOLD,
    _STUCK_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════


def _write_session(tmpdir: str, project_name: str, events: list[dict]) -> Path:
    """Write a fake JSONL session file and return its path."""
    project_dir = Path(tmpdir) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    session_file = project_dir / "session-001.jsonl"
    with open(session_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return session_file


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════


class TestActivityDetectorClassify:
    """Unit tests for the _classify method."""

    def setup_method(self):
        self.detector = ActivityDetector()

    def test_exit_event_returns_exited(self):
        state = self.detector._classify("result", 0, [{"type": "result"}])
        assert state == AgentState.EXITED

    def test_error_event_returns_exited(self):
        state = self.detector._classify("error", 0, [{"type": "error"}])
        assert state == AgentState.EXITED

    def test_blocked_event_returns_blocked(self):
        state = self.detector._classify(
            "permission_request", 10, [{"type": "permission_request"}]
        )
        assert state == AgentState.BLOCKED

    def test_recent_tool_use_returns_active(self):
        state = self.detector._classify("tool_use", 5, [{"type": "tool_use"}])
        assert state == AgentState.ACTIVE

    def test_recent_assistant_returns_idle(self):
        state = self.detector._classify("user", 5, [{"type": "user"}])
        assert state == AgentState.IDLE

    def test_old_activity_with_active_recent_events_returns_active(self):
        """If age > ACTIVE_THRESHOLD but recent events show activity → still active."""
        events = [
            {"type": "assistant"},
            {"type": "tool_use"},
            {"type": "bash"},
        ]
        state = self.detector._classify("bash", _ACTIVE_THRESHOLD + 10, events)
        assert state == AgentState.ACTIVE

    def test_old_activity_without_active_events_returns_stuck(self):
        """If age > ACTIVE_THRESHOLD and no recent active events → stuck."""
        events = [
            {"type": "user"},
            {"type": "user"},
            {"type": "user"},
        ]
        state = self.detector._classify("user", _ACTIVE_THRESHOLD + 10, events)
        assert state == AgentState.STUCK

    def test_very_old_activity_returns_stuck(self):
        """If age > STUCK_THRESHOLD → always stuck."""
        state = self.detector._classify(
            "tool_use", _STUCK_THRESHOLD + 10, [{"type": "tool_use"}]
        )
        assert state == AgentState.STUCK


class TestActivityDetectorDetect:
    """Integration tests for the detect method with real temp files."""

    def test_process_not_alive_returns_exited(self):
        detector = ActivityDetector()
        snapshot = detector.detect("/some/path", process_alive=False)
        assert snapshot.state == AgentState.EXITED

    def test_no_session_file_returns_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = ActivityDetector(claude_projects_dir=tmpdir)
            snapshot = detector.detect("/nonexistent/project", process_alive=True)
            assert snapshot.state == AgentState.UNKNOWN
            assert "No session file" in snapshot.details

    def test_active_session_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = "/home/user/myproject"
            encoded = working_dir.replace("/", "-").lstrip("-")
            _write_session(tmpdir, encoded, [
                {"type": "assistant", "text": "thinking..."},
                {"type": "tool_use", "tool": "edit"},
            ])

            detector = ActivityDetector(claude_projects_dir=tmpdir)
            snapshot = detector.detect(working_dir, process_alive=True)
            assert snapshot.state == AgentState.ACTIVE
            assert snapshot.last_event_type == "tool_use"
            assert "Using tool: edit" in snapshot.details

    def test_exited_session_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = "/home/user/myproject"
            encoded = working_dir.replace("/", "-").lstrip("-")
            _write_session(tmpdir, encoded, [
                {"type": "assistant", "text": "done"},
                {"type": "result", "output": "completed"},
            ])

            detector = ActivityDetector(claude_projects_dir=tmpdir)
            snapshot = detector.detect(working_dir, process_alive=True)
            assert snapshot.state == AgentState.EXITED

    def test_empty_session_returns_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = "/home/user/myproject"
            encoded = working_dir.replace("/", "-").lstrip("-")
            # Empty file
            project_dir = Path(tmpdir) / encoded
            project_dir.mkdir(parents=True)
            (project_dir / "session.jsonl").write_text("")

            detector = ActivityDetector(claude_projects_dir=tmpdir)
            snapshot = detector.detect(working_dir, process_alive=True)
            assert snapshot.state == AgentState.UNKNOWN


class TestSummarize:
    """Tests for the _summarize helper."""

    def setup_method(self):
        self.detector = ActivityDetector()

    def test_tool_use_summary(self):
        s = self.detector._summarize({"type": "tool_use", "tool": "grep"})
        assert "grep" in s

    def test_assistant_summary_truncated(self):
        long_text = "x" * 200
        s = self.detector._summarize({"type": "assistant", "text": long_text})
        assert len(s) < 200
        assert s.endswith("...")

    def test_bash_summary(self):
        s = self.detector._summarize({"type": "bash", "command": "npm test"})
        assert "npm test" in s

    def test_error_summary(self):
        s = self.detector._summarize({"type": "error", "message": "timeout"})
        assert "timeout" in s
