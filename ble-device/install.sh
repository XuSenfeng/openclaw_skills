#!/bin/bash
# Claude Code BLE Device Skill - Installer
# Run this once to set up the skill

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Claude Code BLE Device Skill ==="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"

# Install dependencies
echo ""
echo "Installing Python dependencies..."
pip install -e . --quiet

# Auto-configure Claude Code settings
SETTINGS_FILE="$HOME/.claude/settings.json"
HOOK_PATH="$SCRIPT_DIR/hooks/permission_hook.py"

echo ""
echo "Configuring Claude Code settings..."

# Backup existing settings
if [ -f "$SETTINGS_FILE" ]; then
    cp "$SETTINGS_FILE" "${SETTINGS_FILE}.backup.$(date +%Y%m%d%H%M%S)"
    echo "  Backed up existing settings"
fi

# Create settings directory if needed
mkdir -p "$(dirname "$SETTINGS_FILE")"

# Build new config using Python for proper JSON handling
python3 << PYTHON_SCRIPT
import json
import os

settings_file = os.path.expanduser("~/.claude/settings.json")
hook_path = "$HOOK_PATH"

# Load existing settings or create new
if os.path.exists(settings_file):
    with open(settings_file, 'r') as f:
        settings = json.load(f)
else:
    settings = {}

# Add MCP server
if "mcpServers" not in settings:
    settings["mcpServers"] = {}

settings["mcpServers"]["ble-device"] = {
    "command": "python",
    "args": ["-m", "claude_code_ble_bridge.server"]
}

# Add hooks
if "hooks" not in settings:
    settings["hooks"] = {}

settings["hooks"]["PermissionRequest"] = [{
    "matcher": "Bash|Write|Edit",
    "hooks": [{
        "type": "command",
        "command": f"python {hook_path}",
        "timeout": 120
    }]
}]

# Write settings
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print("  Updated ~/.claude/settings.json")
PYTHON_SCRIPT

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Configuration added:"
echo "  - MCP server: ble-device"
echo "  - Permission hook for: Bash, Write, Edit"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code"
echo "  2. Use 'ble_auto_connect' tool to connect to your device"
echo ""
echo "Press Button A to approve, Button B to deny permissions."
