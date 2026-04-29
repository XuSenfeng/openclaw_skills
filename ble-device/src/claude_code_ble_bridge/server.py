"""
MCP Server for Claude Code BLE Bridge.

Provides tools to connect and interact with Claude Desktop Buddy hardware device.
"""

import asyncio
import logging
import sys
import time
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .ble_client import get_client, BLEClient
from .protocol import (
    build_heartbeat,
    build_time_sync,
    build_command,
)
from .state import DeviceStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# Create MCP server
server = Server("claude-code-ble-bridge")


# Tool definitions
TOOLS = [
    Tool(
        name="ble_scan",
        description="Scan for Claude Desktop Buddy devices nearby",
        inputSchema={
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "number",
                    "description": "Scan timeout in seconds (default: 5)",
                    "default": 5,
                },
            },
        },
    ),
    Tool(
        name="ble_connect",
        description="Connect to a Claude Desktop Buddy device. Auto-selects first found device if address not specified.",
        inputSchema={
            "type": "object",
            "properties": {
                "device_address": {
                    "type": "string",
                    "description": "Device Bluetooth address (auto-select if not specified)",
                },
            },
        },
    ),
    Tool(
        name="ble_disconnect",
        description="Disconnect from the currently connected device",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="ble_status",
        description="Get device status (battery, system info, statistics)",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="send_heartbeat",
        description="Send session state heartbeat to the device",
        inputSchema={
            "type": "object",
            "properties": {
                "total": {
                    "type": "integer",
                    "description": "Total number of sessions",
                    "default": 0,
                },
                "running": {
                    "type": "integer",
                    "description": "Number of running/generating sessions",
                    "default": 0,
                },
                "waiting": {
                    "type": "integer",
                    "description": "Number of sessions waiting for permission",
                    "default": 0,
                },
                "msg": {
                    "type": "string",
                    "description": "Status message (max 24 chars)",
                    "default": "",
                },
                "entries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recent transcript entries (max 8)",
                },
                "tokens": {
                    "type": "integer",
                    "description": "Cumulative token count",
                    "default": 0,
                },
                "tokens_today": {
                    "type": "integer",
                    "description": "Today's token count",
                    "default": 0,
                },
            },
            "required": ["total", "running", "waiting"],
        },
    ),
    Tool(
        name="send_permission_prompt",
        description="Send a permission prompt to the device for user approval",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt_id": {
                    "type": "string",
                    "description": "Unique identifier for this permission request",
                },
                "tool": {
                    "type": "string",
                    "description": "Tool name requesting permission (e.g., 'Bash', 'Write')",
                },
                "hint": {
                    "type": "string",
                    "description": "Hint about what the tool will do",
                },
                "total": {
                    "type": "integer",
                    "description": "Total sessions",
                    "default": 1,
                },
                "running": {
                    "type": "integer",
                    "description": "Running sessions",
                    "default": 0,
                },
                "waiting": {
                    "type": "integer",
                    "description": "Waiting sessions",
                    "default": 1,
                },
            },
            "required": ["prompt_id", "tool", "hint"],
        },
    ),
    Tool(
        name="wait_permission_response",
        description="Wait for permission response from device user",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt_id": {
                    "type": "string",
                    "description": "The prompt ID to wait for response",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 60)",
                    "default": 60,
                },
            },
            "required": ["prompt_id"],
        },
    ),
    Tool(
        name="send_device_command",
        description="Send a command to the device (name, owner, species, unpair)",
        inputSchema={
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Command name",
                    "enum": ["name", "owner", "species", "unpair"],
                },
                "params": {
                    "type": "object",
                    "description": "Command parameters",
                },
            },
            "required": ["cmd"],
        },
    ),
    Tool(
        name="send_time_sync",
        description="Send time synchronization to the device",
        inputSchema={
            "type": "object",
            "properties": {
                "timezone_offset": {
                    "type": "integer",
                    "description": "Timezone offset in seconds (negative for west, e.g., -25200 for PDT)",
                },
            },
        },
    ),
    Tool(
        name="clear_prompt",
        description="Clear the permission prompt from device display",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="request_permission",
        description="One-stop permission request: send prompt and wait for response. Combines send_permission_prompt + wait_permission_response + clear_prompt.",
        inputSchema={
            "type": "object",
            "properties": {
                "prompt_id": {
                    "type": "string",
                    "description": "Unique identifier for this permission request",
                },
                "tool": {
                    "type": "string",
                    "description": "Tool name requesting permission (e.g., 'Bash', 'Write')",
                },
                "hint": {
                    "type": "string",
                    "description": "Hint about what the tool will do",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 60)",
                    "default": 60,
                },
            },
            "required": ["prompt_id", "tool", "hint"],
        },
    ),
    Tool(
        name="ble_auto_connect",
        description="Auto-connect to the first available Claude device and sync time",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    client = get_client()

    try:
        if name == "ble_scan":
            result = await handle_scan(client, arguments)
        elif name == "ble_connect":
            result = await handle_connect(client, arguments)
        elif name == "ble_disconnect":
            result = await handle_disconnect(client, arguments)
        elif name == "ble_status":
            result = await handle_status(client, arguments)
        elif name == "send_heartbeat":
            result = await handle_heartbeat(client, arguments)
        elif name == "send_permission_prompt":
            result = await handle_permission_prompt(client, arguments)
        elif name == "wait_permission_response":
            result = await handle_wait_permission(client, arguments)
        elif name == "send_device_command":
            result = await handle_device_command(client, arguments)
        elif name == "send_time_sync":
            result = await handle_time_sync(client, arguments)
        elif name == "clear_prompt":
            result = await handle_clear_prompt(client, arguments)
        elif name == "request_permission":
            result = await handle_request_permission(client, arguments)
        elif name == "ble_auto_connect":
            result = await handle_auto_connect(client, arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.exception(f"Tool {name} failed")
        result = {"error": str(e)}

    return [TextContent(type="text", text=format_result(result))]


def format_result(result: Any) -> str:
    """Format result as JSON string."""
    import json

    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, default=str)


async def handle_scan(client: BLEClient, args: dict) -> dict:
    """Handle ble_scan tool."""
    timeout = args.get("timeout", 5.0)
    devices = await client.scan(timeout=timeout)

    if not devices:
        return {"found": 0, "devices": [], "message": "No Claude devices found"}

    return {
        "found": len(devices),
        "devices": devices,
    }


async def handle_connect(client: BLEClient, args: dict) -> dict:
    """Handle ble_connect tool."""
    if client.connected:
        return {
            "connected": True,
            "device_name": client.device_name,
            "device_address": client.device_address,
            "message": "Already connected",
        }

    device_address = args.get("device_address")
    result = await client.connect(device_address=device_address)

    # Send time sync after connection
    try:
        tz_offset = time.localtime().tm_gmtoff
        epoch = int(time.time())
        await client.send(build_time_sync(epoch, int(tz_offset)))
        logger.info("Sent time sync")
    except Exception as e:
        logger.warning(f"Failed to send time sync: {e}")

    return result


async def handle_disconnect(client: BLEClient, args: dict) -> dict:
    """Handle ble_disconnect tool."""
    return await client.disconnect()


async def handle_status(client: BLEClient, args: dict) -> dict:
    """Handle ble_status tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    status = await client.get_status()
    return {
        "name": status.name,
        "owner": status.owner,
        "secure": status.secure,
        "battery": {
            "percent": status.battery.percent,
            "millivolts": status.battery.millivolts,
            "milliamps": status.battery.milliamps,
            "usb_connected": status.battery.usb_connected,
        },
        "system": {
            "uptime_seconds": status.system.uptime_seconds,
            "heap_free": status.system.heap_free,
            "fs_free": status.system.fs_free,
            "fs_total": status.system.fs_total,
        },
        "stats": {
            "approvals": status.stats.approvals,
            "denials": status.stats.denials,
            "velocity": status.stats.velocity,
            "nap_seconds": status.stats.nap_seconds,
            "level": status.stats.level,
        },
    }


async def handle_heartbeat(client: BLEClient, args: dict) -> dict:
    """Handle send_heartbeat tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    message = build_heartbeat(
        total=args.get("total", 0),
        running=args.get("running", 0),
        waiting=args.get("waiting", 0),
        msg=args.get("msg", ""),
        entries=args.get("entries"),
        tokens=args.get("tokens", 0),
        tokens_today=args.get("tokens_today", 0),
    )

    success = await client.send(message)
    return {"sent": success}


async def handle_permission_prompt(client: BLEClient, args: dict) -> dict:
    """Handle send_permission_prompt tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    prompt_id = args["prompt_id"]
    tool = args["tool"]
    hint = args["hint"]

    message = build_heartbeat(
        total=args.get("total", 1),
        running=args.get("running", 0),
        waiting=args.get("waiting", 1),
        msg=f"approve: {tool}"[:24],
        prompt_id=prompt_id,
        prompt_tool=tool,
        prompt_hint=hint,
    )

    success = await client.send(message)
    return {
        "sent": success,
        "prompt_id": prompt_id,
        "tool": tool,
        "hint": hint,
        "message": "Permission prompt sent. Use wait_permission_response to get the decision.",
    }


async def handle_wait_permission(client: BLEClient, args: dict) -> dict:
    """Handle wait_permission_response tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    prompt_id = args["prompt_id"]
    timeout = args.get("timeout", 60.0)

    # wait_permission_response will auto-clear prompt after receiving response
    response = await client.wait_permission_response(prompt_id, timeout, clear_after=True)

    if response is None:
        return {
            "timeout": True,
            "prompt_id": prompt_id,
            "decision": None,
            "message": f"No response received within {timeout} seconds",
        }

    return {
        "timeout": False,
        "prompt_id": response.prompt_id,
        "decision": response.decision,
        "approved": response.decision == "once",
        "denied": response.decision == "deny",
        "message": f"User {'approved' if response.decision == 'once' else 'denied'} the request. Prompt cleared from device.",
    }


async def handle_device_command(client: BLEClient, args: dict) -> dict:
    """Handle send_device_command tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    cmd = args["cmd"]
    params = args.get("params", {})

    message = build_command(cmd, **params)
    success = await client.send(message)

    return {
        "sent": success,
        "command": cmd,
        "params": params,
    }


async def handle_time_sync(client: BLEClient, args: dict) -> dict:
    """Handle send_time_sync tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    if "timezone_offset" in args:
        tz_offset = args["timezone_offset"]
    else:
        tz_offset = time.localtime().tm_gmtoff

    epoch = int(time.time())
    message = build_time_sync(epoch, int(tz_offset))
    success = await client.send(message)

    return {
        "sent": success,
        "epoch": epoch,
        "timezone_offset": tz_offset,
    }


async def handle_clear_prompt(client: BLEClient, args: dict) -> dict:
    """Handle clear_prompt tool."""
    if not client.connected:
        return {"error": "Not connected to device"}

    success = await client.clear_prompt()
    return {"cleared": success}


async def handle_request_permission(client: BLEClient, args: dict) -> dict:
    """Handle request_permission tool - combined send + wait + clear."""
    if not client.connected:
        return {"error": "Not connected to device"}

    prompt_id = args["prompt_id"]
    tool = args["tool"]
    hint = args["hint"]
    timeout = args.get("timeout", 60.0)

    # Send prompt
    message = build_heartbeat(
        total=1,
        running=0,
        waiting=1,
        msg=f"approve: {tool}"[:24],
        prompt_id=prompt_id,
        prompt_tool=tool,
        prompt_hint=hint,
    )
    await client.send(message)

    # Wait for response (will auto-clear prompt)
    response = await client.wait_permission_response(prompt_id, timeout, clear_after=True)

    if response is None:
        return {
            "timeout": True,
            "prompt_id": prompt_id,
            "decision": None,
            "approved": False,
            "message": f"No response received within {timeout} seconds",
        }

    return {
        "timeout": False,
        "prompt_id": response.prompt_id,
        "decision": response.decision,
        "approved": response.decision == "once",
        "denied": response.decision == "deny",
        "message": f"User {'approved' if response.decision == 'once' else 'denied'} the request",
    }


async def handle_auto_connect(client: BLEClient, args: dict) -> dict:
    """Handle ble_auto_connect tool."""
    if client.connected:
        return {
            "connected": True,
            "device_name": client.device_name,
            "device_address": client.device_address,
            "message": "Already connected",
        }

    # Scan and connect to first device
    devices = await client.scan(timeout=5.0)
    if not devices:
        return {"connected": False, "error": "No Claude devices found"}

    result = await client.connect(devices[0]["address"])

    # Send time sync
    try:
        tz_offset = time.localtime().tm_gmtoff
        epoch = int(time.time())
        await client.send(build_time_sync(epoch, int(tz_offset)))
    except Exception as e:
        logger.warning(f"Failed to send time sync: {e}")

    result["auto_selected"] = True
    result["message"] = f"Auto-connected to {result['device_name']}"
    return result


async def run_server():
    """Run the MCP server."""
    logger.info("Starting Claude Code BLE Bridge MCP Server")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Main entry point."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
