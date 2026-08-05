#!/bin/bash
# Installs the nv-mcp LaunchAgent into the current user's GUI session.
# Usage: scripts/install-launchagent.sh [port]   (default 8765)
set -euo pipefail

PORT="${1:-8765}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.llm-secret-manager.mcp"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__REPO__|$REPO|g" -e "s|__PORT__|$PORT|g" \
	"$REPO/launchd/$LABEL.plist.template" > "$PLIST"

# Reload cleanly if it was already installed.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

sleep 1
if curl -s -o /dev/null "http://127.0.0.1:$PORT/mcp" -X POST \
	-H 'Content-Type: application/json' \
	-d '{"jsonrpc":"2.0","id":1,"method":"ping"}'; then
	echo "nv-mcp running on http://127.0.0.1:$PORT/mcp"
else
	echo "installed, but the server did not answer yet — check /tmp/llm-secret-manager-mcp.log" >&2
	exit 1
fi
