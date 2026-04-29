# BLE Device Permission Approval

Connect Claude Code to Claude Desktop Buddy hardware device for button-based permission approval.

## What it does

- **Automatic**: Intercepts permission requests and sends them to your device
- You approve/deny by pressing buttons on the device
- Auto-clears prompt after decision
- Syncs session state to device display

## Setup

### 1. Install the skill

```bash
cd ble-device
./install.sh
```

### 2. Configure Claude Code settings

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
        "command": "python /path/to/ble-device/hooks/permission_hook.py",
        "timeout": 120
      }]
    }]
  }
}
```

Replace `/path/to/ble-device` with the actual path.

## How it works

1. Claude Code needs permission for a tool (Bash, Write, Edit)
2. Hook triggers automatically
3. Permission request is sent to your BLE device
4. Device shows tool name and hint
5. You press **Button A** (approve) or **Button B** (deny)
6. Decision is sent back to Claude Code
7. Prompt auto-clears from device

## Manual Tools (Optional)

If you prefer manual control, use these MCP tools:

| Tool | Purpose |
|------|---------|
| `ble_auto_connect` | Auto-connect to device |
| `request_permission` | Manual permission request |
| `ble_status` | Check battery/status |
| `send_heartbeat` | Update device display |

## Files

```
ble-device/
├── skill.md           # This file
├── install.sh         # Installation script
├── hooks/
│   └── permission_hook.py  # Auto-permission hook
├── src/               # BLE bridge source
└── example/           # Config examples
```
