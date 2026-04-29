"""
JSON protocol for Claude Desktop Buddy communication.

All messages are line-delimited JSON (ending with '\\n').
"""

import json
from dataclasses import dataclass
from typing import Any, Optional


# BLE NUS UUIDs
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # Write to device
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # Notify from device

# Device name prefix for scanning
DEVICE_NAME_PREFIX = "Claude"


@dataclass
class HeartbeatMessage:
    """Heartbeat/state update message sent to device."""
    total: int = 0
    running: int = 0
    waiting: int = 0
    msg: str = ""
    entries: list[str] | None = None
    tokens: int = 0
    tokens_today: int = 0
    prompt_id: Optional[str] = None
    prompt_tool: Optional[str] = None
    prompt_hint: Optional[str] = None


@dataclass
class PermissionDecision:
    """Permission decision from device."""
    prompt_id: str
    decision: str  # "once" or "deny"


@dataclass
class AckResponse:
    """Acknowledgment response from device."""
    command: str
    ok: bool
    n: int = 0
    error: Optional[str] = None
    data: Optional[dict[str, Any]] = None


def build_heartbeat(
    total: int = 0,
    running: int = 0,
    waiting: int = 0,
    msg: str = "",
    entries: list[str] | None = None,
    tokens: int = 0,
    tokens_today: int = 0,
    prompt_id: Optional[str] = None,
    prompt_tool: Optional[str] = None,
    prompt_hint: Optional[str] = None,
) -> bytes:
    """
    Build a heartbeat/state update message.

    Args:
        total: Total number of sessions
        running: Number of running sessions
        waiting: Number of sessions waiting for permission
        msg: Status message (max 24 chars)
        entries: List of transcript lines (max 8)
        tokens: Cumulative token count
        tokens_today: Today's token count
        prompt_id: Permission prompt ID (if waiting for approval)
        prompt_tool: Tool name requesting permission
        prompt_hint: Hint about what the tool will do

    Returns:
        JSON message as bytes with newline terminator
    """
    data: dict[str, Any] = {
        "total": total,
        "running": running,
        "waiting": waiting,
        "msg": msg[:24],  # Truncate to 24 chars
    }

    if entries:
        data["entries"] = entries[:8]  # Max 8 entries

    data["tokens"] = tokens
    data["tokens_today"] = tokens_today

    if prompt_id:
        data["prompt"] = {
            "id": prompt_id,
            "tool": prompt_tool or "",
            "hint": prompt_hint or "",
        }

    return (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")


def build_time_sync(epoch: int, timezone_offset: int) -> bytes:
    """
    Build a time sync message.

    Args:
        epoch: Unix timestamp (seconds)
        timezone_offset: Timezone offset in seconds (negative for west)

    Returns:
        JSON message as bytes with newline terminator
    """
    data = {"time": [epoch, timezone_offset]}
    return (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")


def build_permission_prompt(
    prompt_id: str,
    tool: str,
    hint: str,
) -> bytes:
    """
    Build a permission prompt message (sends as part of heartbeat).

    This is a convenience function that wraps build_heartbeat.
    """
    return build_heartbeat(
        prompt_id=prompt_id,
        prompt_tool=tool,
        prompt_hint=hint,
        msg=f"approve: {tool}",
    )


def build_command(cmd: str, **params: Any) -> bytes:
    """
    Build a command message.

    Args:
        cmd: Command name (status, name, owner, species, unpair)
        **params: Command parameters

    Returns:
        JSON message as bytes with newline terminator
    """
    data = {"cmd": cmd, **params}
    return (json.dumps(data, separators=(",", ":")) + "\n").encode("utf-8")


def build_permission_response(prompt_id: str, decision: str) -> bytes:
    """
    Build a permission response message (for testing/simulation).

    Args:
        prompt_id: The prompt ID being responded to
        decision: "once" (approve) or "deny"

    Returns:
        JSON message as bytes with newline terminator
    """
    return build_command("permission", id=prompt_id, decision=decision)


def parse_message(data: bytes) -> dict[str, Any] | None:
    """
    Parse a JSON message from raw bytes.

    Args:
        data: Raw bytes (should be a complete JSON line)

    Returns:
        Parsed dict or None if invalid
    """
    try:
        text = data.decode("utf-8").strip()
        if not text or not text.startswith("{"):
            return None
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def parse_ack(data: dict[str, Any]) -> AckResponse | None:
    """
    Parse an acknowledgment response.

    Args:
        data: Parsed JSON dict

    Returns:
        AckResponse or None if not an ack
    """
    if "ack" not in data:
        return None

    return AckResponse(
        command=data["ack"],
        ok=data.get("ok", False),
        n=data.get("n", 0),
        error=data.get("error"),
        data=data.get("data"),
    )


def parse_permission_decision(data: dict[str, Any]) -> PermissionDecision | None:
    """
    Parse a permission decision from device.

    Args:
        data: Parsed JSON dict

    Returns:
        PermissionDecision or None if not a permission response
    """
    if data.get("cmd") != "permission":
        return None

    return PermissionDecision(
        prompt_id=data.get("id", ""),
        decision=data.get("decision", ""),
    )
