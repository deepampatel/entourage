"""Resource monitor — gates parallel task dispatch on system resources.

Checks CPU, memory, and disk usage before allowing new tasks to be dispatched.
This prevents overloading the host when running multiple agents in parallel.

Learn: psutil provides cross-platform system metrics. We use non-blocking
percent() calls with interval=None for instant snapshots (suitable for
the polling loop in ExecutionLoop).
"""

import logging
from typing import Optional

logger = logging.getLogger("openclaw.services.resource_monitor")


class ResourceMonitor:
    """Check system resources before dispatching pipeline tasks."""

    CPU_THRESHOLD: float = 90.0
    MEMORY_THRESHOLD: float = 90.0
    DISK_THRESHOLD: float = 95.0

    def can_dispatch(self) -> tuple[bool, str]:
        """Check CPU, memory, and disk usage.

        Returns (ok, reason). If ok=False, reason explains the bottleneck.
        Gracefully degrades if psutil is not installed — always allows dispatch.
        """
        psutil = self._get_psutil()
        if psutil is None:
            return True, "psutil not available, skipping resource checks"

        # CPU — instant snapshot (interval=None = non-blocking)
        cpu = psutil.cpu_percent(interval=None)
        if cpu > self.CPU_THRESHOLD:
            reason = f"CPU usage {cpu:.1f}% exceeds {self.CPU_THRESHOLD}% threshold"
            logger.warning(reason)
            return False, reason

        # Memory
        mem = psutil.virtual_memory()
        if mem.percent > self.MEMORY_THRESHOLD:
            reason = (
                f"Memory usage {mem.percent:.1f}% exceeds "
                f"{self.MEMORY_THRESHOLD}% threshold"
            )
            logger.warning(reason)
            return False, reason

        # Disk
        disk = psutil.disk_usage("/")
        if disk.percent > self.DISK_THRESHOLD:
            reason = (
                f"Disk usage {disk.percent:.1f}% exceeds "
                f"{self.DISK_THRESHOLD}% threshold"
            )
            logger.warning(reason)
            return False, reason

        return True, "ok"

    @staticmethod
    def _get_psutil() -> Optional[object]:
        """Import psutil lazily — it's an optional dependency."""
        try:
            import psutil
            return psutil
        except ImportError:
            logger.debug("psutil not installed, resource monitoring disabled")
            return None
