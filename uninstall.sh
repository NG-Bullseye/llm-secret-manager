#!/usr/bin/env bash
#
# Removes the hook entry from settings.json and the installed files.
# Keychain items are never touched.

set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local/bin}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"

# Remove both spellings: install.sh writes a literal $HOME for the default
# location and an absolute path for a custom CLAUDE_CONFIG_DIR.
HOOK_CMD='$HOME/.claude/hooks/guard-secrets.sh'
HOOK_CMD_ABS="$CLAUDE_DIR/hooks/guard-secrets.sh"

say() { printf '%s\n' "$1"; }

if [ -f "$SETTINGS" ] && jq -e . "$SETTINGS" >/dev/null 2>&1; then
	backup="$SETTINGS.bak.$(date +%Y%m%d%H%M%S)"
	cp "$SETTINGS" "$backup"
	tmp="$(mktemp)"
	jq --arg cmd "$HOOK_CMD" --arg abs "$HOOK_CMD_ABS" '
	  if .hooks.PreToolUse then
	    .hooks.PreToolUse |= map(.hooks |= map(select(.command != $cmd and .command != $abs)))
	    | .hooks.PreToolUse |= map(select((.hooks | length) > 0))
	  else . end
	' "$SETTINGS" > "$tmp"
	mv "$tmp" "$SETTINGS"
	say "hook entry removed from $SETTINGS (backup: $backup)"
fi

rm -f "$CLAUDE_DIR/hooks/guard-secrets.sh" && say "removed: $CLAUDE_DIR/hooks/guard-secrets.sh"
rm -f "$PREFIX/with-secrets" && say "removed: $PREFIX/with-secrets"

say ""
say "Keychain items were not touched."
say "Repo-local copies (scripts/with-secrets) are yours to remove."
