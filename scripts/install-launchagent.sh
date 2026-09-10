#!/bin/bash
# Installs the nv-mcp LaunchAgent into the current user's GUI session.
# Usage: scripts/install-launchagent.sh [port]   (default 8765)
#
# Set BWV_BOOTSTRAP to the keychain item holding the Bitwarden master password
# to enable the bw_* tools:
#   BWV_BOOTSTRAP=my-bitwarden scripts/install-launchagent.sh
# It is an item name, not a secret, so it is fine in the plist. Without it the
# keychain-only secret_* tools still work.
set -euo pipefail

PORT="${1:-8765}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.llm-secret-manager.mcp"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BOOTSTRAP="${BWV_BOOTSTRAP:-}"

[ -n "$BOOTSTRAP" ] || echo "note: BWV_BOOTSTRAP unset - the bw_* (Bitwarden) tools will not be able to unlock" >&2

mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__REPO__|$REPO|g" -e "s|__PORT__|$PORT|g" \
	-e "s|__BWV_BOOTSTRAP__|$BOOTSTRAP|g" \
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
