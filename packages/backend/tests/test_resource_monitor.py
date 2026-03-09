"""Tests for ResourceMonitor service."""

from unittest.mock import MagicMock, patch

import pytest

from openclaw.services.resource_monitor import ResourceMonitor


class TestCanDispatch:
    """Test the can_dispatch resource gating."""

    def test_can_dispatch_ok(self):
        """When all resources are within thresholds, dispatch is allowed."""
        monitor = ResourceMonitor()

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 50.0
        mock_psutil.virtual_memory.return_value = MagicMock(percent=60.0)
        mock_psutil.disk_usage.return_value = MagicMock(percent=70.0)

        with patch.object(ResourceMonitor, "_get_psutil", return_value=mock_psutil):
            ok, reason = monitor.can_dispatch()

        assert ok is True
        assert reason == "ok"

    def test_blocks_high_cpu(self):
        """When CPU exceeds threshold, dispatch is blocked."""
        monitor = ResourceMonitor()

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 95.0

        with patch.object(ResourceMonitor, "_get_psutil", return_value=mock_psutil):
            ok, reason = monitor.can_dispatch()

        assert ok is False
        assert "CPU usage" in reason
        assert "95.0%" in reason

    def test_blocks_high_memory(self):
        """When memory exceeds threshold, dispatch is blocked."""
        monitor = ResourceMonitor()

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 50.0
        mock_psutil.virtual_memory.return_value = MagicMock(percent=92.5)

        with patch.object(ResourceMonitor, "_get_psutil", return_value=mock_psutil):
            ok, reason = monitor.can_dispatch()

        assert ok is False
        assert "Memory usage" in reason
        assert "92.5%" in reason

    def test_blocks_high_disk(self):
        """When disk exceeds threshold, dispatch is blocked."""
        monitor = ResourceMonitor()

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 50.0
        mock_psutil.virtual_memory.return_value = MagicMock(percent=60.0)
        mock_psutil.disk_usage.return_value = MagicMock(percent=97.0)

        with patch.object(ResourceMonitor, "_get_psutil", return_value=mock_psutil):
            ok, reason = monitor.can_dispatch()

        assert ok is False
        assert "Disk usage" in reason
        assert "97.0%" in reason

    def test_graceful_without_psutil(self):
        """When psutil is not installed, dispatch is always allowed."""
        monitor = ResourceMonitor()

        with patch.object(ResourceMonitor, "_get_psutil", return_value=None):
            ok, reason = monitor.can_dispatch()

        assert ok is True
        assert "psutil not available" in reason

    def test_exact_threshold_allows(self):
        """Values exactly at the threshold should allow dispatch."""
        monitor = ResourceMonitor()

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 90.0  # Exactly at threshold
        mock_psutil.virtual_memory.return_value = MagicMock(percent=90.0)
        mock_psutil.disk_usage.return_value = MagicMock(percent=95.0)

        with patch.object(ResourceMonitor, "_get_psutil", return_value=mock_psutil):
            ok, reason = monitor.can_dispatch()

        assert ok is True
        assert reason == "ok"

    def test_custom_thresholds(self):
        """Custom thresholds can be set."""
        monitor = ResourceMonitor()
        monitor.CPU_THRESHOLD = 50.0

        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 55.0

        with patch.object(ResourceMonitor, "_get_psutil", return_value=mock_psutil):
            ok, reason = monitor.can_dispatch()

        assert ok is False
        assert "CPU usage" in reason
