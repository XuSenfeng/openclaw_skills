#!/usr/bin/env python3
"""
BLE Permission Hook for Claude Code.
Called automatically when Claude Code needs permission approval.

Input (stdin): JSON with tool_name, tool_input
Output: JSON with permissionDecision ("allow", "deny", or "ask")
"""

import asyncio
import json
import logging
import sys
import time
import uuid

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Import BLE client
try:
    from claude_code_ble_bridge import BLEClient, build_heartbeat
except ImportError:
    # Try relative import if not installed
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.claude_code_ble_bridge import BLEClient, build_heartbeat


# Global client (persists across calls)
_client: BLEClient = None


async def get_client() -> BLEClient:
    """Get or create BLE client, auto-connect if needed."""
    global _client

    if _client is None:
        _client = BLEClient()

    if not _client.connected:
        # Auto-connect to first available device
        try:
            await _client.connect()
        except Exception as e:
            print(f"BLE connection failed: {e}", file=sys.stderr)
            return None

    return _client


async def request_ble_permission(tool_name: str, hint: str, timeout: float = 60.0) -> str:
    """
    Request permission via BLE device.

    Returns:
        "allow", "deny", or "ask" (if timeout/error)
    """
    client = await get_client()
    if client is None:
        logger.warning("BLE client unavailable, falling back to desktop")
        return "ask"  # Fall back to default prompt

    prompt_id = f"hook-{uuid.uuid4().hex[:8]}"
    logger.info(f"Requesting permission: tool={tool_name}, prompt_id={prompt_id}")

    # Send permission prompt
    msg = build_heartbeat(
        total=1,
        running=0,
        waiting=1,
        msg=f"approve: {tool_name}"[:24],
        prompt_id=prompt_id,
        prompt_tool=tool_name,
        prompt_hint=hint[:44],  # Max 44 chars
    )

    logger.debug(f"Sending message: {msg}")

    try:
        await client.send(msg)
        logger.info("Permission request sent to device")
    except Exception as e:
        logger.error(f"BLE send failed: {e}")
        return "ask"

    # Wait for response
    logger.info(f"Waiting for response (timeout={timeout}s)...")
    response = await client.wait_permission_response(prompt_id, timeout, clear_after=True)

    if response is None:
        logger.warning("BLE permission timeout - no response from device")
        return "ask"

    logger.info(f"Received response: prompt_id={response.prompt_id}, decision={response.decision}")

    # Map device decision to Claude Code decision
    if response.decision == "once":
        return "allow"
    elif response.decision == "deny":
        return "deny"
    else:
        return "ask"


def main():
    logger.info("=== BLE Permission Hook Started ===")

    # Debug: write to temp file
    debug_file = open("/tmp/ble_hook_debug.log", "a")
    debug_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    debug_file.flush()

    # Read input from stdin
    try:
        input_data = json.load(sys.stdin)
        debug_file.write(f"Input: {json.dumps(input_data)}\n")
        debug_file.flush()
    except json.JSONDecodeError:
        logger.error("Failed to parse stdin JSON")
        debug_file.write("ERROR: Failed to parse stdin JSON\n")
        debug_file.close()
        print(json.dumps({"permissionDecision": "ask"}))
        return

    tool_name = input_data.get("tool_name", "Unknown")
    tool_input = input_data.get("tool_input", {})

    logger.info(f"Tool request: {tool_name}")
    debug_file.write(f"Tool: {tool_name}\n")
    debug_file.flush()

    # Build hint from tool input
    hint = ""
    if tool_name == "Bash":
        hint = tool_input.get("command", "")[:44]
    elif tool_name in ("Write", "Edit"):
        hint = tool_input.get("file_path", "")[:44]
    elif tool_name == "Read":
        hint = tool_input.get("file_path", "")[:44]
    else:
        hint = str(tool_input)[:44]

    logger.info(f"Hint: {hint}")

    # Run async permission request
    decision = asyncio.run(request_ble_permission(tool_name, hint))

    logger.info(f"Final decision: {decision}")
    debug_file.write(f"Decision: {decision}\n")
    debug_file.flush()

    # Output JSON response for PreToolUse hook
    # Must use hookSpecificOutput with hookEventName
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision
        }
    }
    logger.info(f"Output: {json.dumps(output)}")
    debug_file.write(f"Output: {json.dumps(output)}\n")
    debug_file.close()
    print(json.dumps(output))


if __name__ == "__main__":
    main()
