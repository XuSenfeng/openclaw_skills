"""
Claude Code BLE Bridge - MCP server for Claude Desktop Buddy hardware device.
"""

__version__ = "0.1.0"

from .protocol import (
    build_heartbeat,
    build_time_sync,
    build_permission_prompt,
    build_command,
    parse_message,
    parse_ack,
)
from .ble_client import BLEClient
from .state import DeviceStatus, PermissionResponse

__all__ = [
    "__version__",
    "build_heartbeat",
    "build_time_sync",
    "build_permission_prompt",
    "build_command",
    "parse_message",
    "parse_ack",
    "BLEClient",
    "DeviceStatus",
    "PermissionResponse",
]
