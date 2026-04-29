"""
State management for BLE device connection.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class BatteryInfo:
    """Device battery information."""
    percent: int = 0
    millivolts: int = 0
    milliamps: int = 0
    usb_connected: bool = False


@dataclass
class SystemInfo:
    """Device system information."""
    uptime_seconds: int = 0
    heap_free: int = 0
    fs_free: int = 0
    fs_total: int = 0


@dataclass
class StatsInfo:
    """Device statistics."""
    approvals: int = 0
    denials: int = 0
    velocity: int = 0  # Median response speed
    nap_seconds: int = 0
    level: int = 0


@dataclass
class DeviceStatus:
    """Complete device status."""
    name: str = ""
    owner: str = ""
    secure: bool = False
    battery: BatteryInfo = field(default_factory=BatteryInfo)
    system: SystemInfo = field(default_factory=SystemInfo)
    stats: StatsInfo = field(default_factory=StatsInfo)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceStatus":
        """Create DeviceStatus from parsed JSON response."""
        bat = data.get("bat", {})
        sys = data.get("sys", {})
        stats = data.get("stats", {})

        return cls(
            name=data.get("name", ""),
            owner=data.get("owner", ""),
            secure=data.get("sec", False),
            battery=BatteryInfo(
                percent=bat.get("pct", 0),
                millivolts=bat.get("mV", 0),
                milliamps=bat.get("mA", 0),
                usb_connected=bat.get("usb", False),
            ),
            system=SystemInfo(
                uptime_seconds=sys.get("up", 0),
                heap_free=sys.get("heap", 0),
                fs_free=sys.get("fsFree", 0),
                fs_total=sys.get("fsTotal", 0),
            ),
            stats=StatsInfo(
                approvals=stats.get("appr", 0),
                denials=stats.get("deny", 0),
                velocity=stats.get("vel", 0),
                nap_seconds=stats.get("nap", 0),
                level=stats.get("lvl", 0),
            ),
        )


@dataclass
class PermissionResponse:
    """Permission response from device."""
    prompt_id: str
    decision: str  # "once" or "deny"
    timestamp: datetime = field(default_factory=datetime.now)


class ConnectionState:
    """Manages BLE connection state and permission response handling."""

    def __init__(self):
        self.connected = False
        self.device_address: Optional[str] = None
        self.device_name: Optional[str] = None
        self.mtu: int = 23  # Default BLE MTU
        self.secure: bool = False

        # Permission response handling
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self._last_heartbeat: Optional[datetime] = None

        # Device status cache
        self._status: Optional[DeviceStatus] = None

    def reset(self):
        """Reset connection state."""
        self.connected = False
        self.device_address = None
        self.device_name = None
        self.mtu = 23
        self.secure = False
        self._status = None
        self._last_heartbeat = None

        # Cancel any pending permission requests
        for future in self._pending_permissions.values():
            if not future.done():
                future.cancel()
        self._pending_permissions.clear()

    def update_heartbeat_time(self):
        """Update last heartbeat timestamp."""
        self._last_heartbeat = datetime.now()

    @property
    def is_heartbeat_timeout(self) -> bool:
        """Check if heartbeat has timed out (30 seconds)."""
        if self._last_heartbeat is None:
            return True
        elapsed = (datetime.now() - self._last_heartbeat).total_seconds()
        return elapsed > 30

    def set_status(self, status: DeviceStatus):
        """Cache device status."""
        self._status = status

    @property
    def status(self) -> Optional[DeviceStatus]:
        """Get cached device status."""
        return self._status

    async def wait_permission_response(
        self,
        prompt_id: str,
        timeout: float = 60.0,
    ) -> Optional[PermissionResponse]:
        """
        Wait for a permission response from the device.

        Args:
            prompt_id: The prompt ID to wait for
            timeout: Timeout in seconds

        Returns:
            PermissionResponse or None if timeout/cancelled
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_permissions[prompt_id] = future

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_permissions.pop(prompt_id, None)

    def handle_permission_response(self, response: PermissionResponse):
        """Handle incoming permission response."""
        future = self._pending_permissions.get(response.prompt_id)
        if future and not future.done():
            future.set_result(response)

    @property
    def max_payload_size(self) -> int:
        """Get maximum payload size based on MTU."""
        return self.mtu - 3  # ATT header overhead
