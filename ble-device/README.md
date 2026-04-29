# Claude Code BLE Device Skill

Connect Claude Code to your Claude Desktop Buddy hardware device for physical button-based permission approval.

## Quick Start

### 1. Install

```bash
cd ble-device
./install.sh
```

### 2. Configure Claude Code

Edit `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "ble-device": {
      "command": "python",
      "args": ["-m", "claude_code_ble_bridge.server"]
    }
  },
  "hooks": {
    "PermissionRequest": [{
      "matcher": "Bash|Write|Edit",
      "hooks": [{
        "type": "command",
        "command": "python /ABSOLUTE/PATH/TO/ble-device/hooks/permission_hook.py",
        "timeout": 120
      }]
    }]
  }
}
```

**Important**: Replace `/ABSOLUTE/PATH/TO/ble-device` with the actual absolute path to this skill folder.

### 3. Restart Claude Code

After updating settings, restart Claude Code for the hook to take effect.

## How It Works

```
┌─────────────┐     PermissionRequest      ┌─────────────┐
│ Claude Code │ ─────────────────────────► │ BLE Hook    │
│             │                            │             │
│             │     permissionDecision     │ BLE Device  │
│             │ ◄───────────────────────── │ (buttons)   │
└─────────────┘                            └─────────────┘
```

1. Claude Code needs permission for Bash/Write/Edit
2. Hook triggers automatically
3. Request sent to your BLE device
4. Device displays tool name and hint
5. Press **Button A** to approve or **Button B** to deny
6. Decision returns to Claude Code
7. Prompt auto-clears from device

## Files

```
ble-device/
├── skill.md              # Skill definition
├── install.sh            # Installation script
├── README.md             # This file
├── pyproject.toml        # Python package config
├── hooks/
│   └── permission_hook.py  # Auto-permission hook
├── src/
│   └── claude_code_ble_bridge/
│       ├── server.py     # MCP server (manual tools)
│       ├── ble_client.py # BLE connection
│       ├── protocol.py   # Protocol implementation
│       └── state.py      # State management
└── example/
    └── mcp_settings.json # Configuration example
```

## Manual Tools (MCP)

If you need manual control:

| Tool | Description |
|------|-------------|
| `ble_auto_connect` | Auto-connect to device |
| `ble_scan` | Scan for devices |
| `ble_status` | Battery & system info |
| `request_permission` | Manual permission request |
| `send_heartbeat` | Update display |
| `clear_prompt` | Clear device display |

## Customization

### Change which tools trigger the hook

Modify the `matcher` in settings.json:

```json
"matcher": "Bash|Write|Edit|Read|Agent"
```

### Adjust timeout

```json
"timeout": 60  // seconds to wait for device response
```

### Add status message

```json
"statusMessage": "Press button on device..."
```

## Troubleshooting

**Hook not triggering**:
- Ensure absolute path in command
- Restart Claude Code after config change
- Check JSON syntax with `jq -e . ~/.claude/settings.json`

**Device not found**:
- Ensure device is powered on
- Check Bluetooth is enabled
- Try `ble_scan` tool manually

**Permission timeout**:
- Device may be out of range
- Increase timeout in settings

## Distributing to Others

Just copy the entire `ble-device` folder:

```bash
# Copy to target machine
scp -r ble-device user@target:/path/to/

# On target machine
cd /path/to/ble-device
./install.sh

# Edit ~/.claude/settings.json with the correct path
```

## License

MIT
