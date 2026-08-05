#!/usr/bin/env bash
#
# Installs with-secrets and the PreToolUse guard hook.
#
#   ./install.sh                       into ~/.local/bin and ~/.claude
#   PREFIX=~/bin ./install.sh          different location for with-secrets
#   CLAUDE_CONFIG_DIR=... ./install.sh non-standard Claude Code config dir
#
# Idempotent: running it repeatedly does not create a duplicate hook entry and
# leaves unrelated hooks in settings.json untouched.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local/bin}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOK_DIR="$CLAUDE_DIR/hooks"
SETTINGS="$CLAUDE_DIR/settings.json"

# For the default location, write a literal $HOME into settings.json so the file
# stays valid across machines. For a custom CLAUDE_CONFIG_DIR the absolute path
# has to go in, otherwise the entry points nowhere.
if [ "$CLAUDE_DIR" = "$HOME/.claude" ]; then
	HOOK_CMD='$HOME/.claude/hooks/guard-secrets.sh'
else
	HOOK_CMD="$HOOK_DIR/guard-secrets.sh"
fi

say() { printf '%s\n' "$1"; }
die() { printf 'install: %s\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "macOS only - 'security' does not exist elsewhere"
command -v jq >/dev/null || die "jq is missing (brew install jq)"

# --- with-secrets ---
mkdir -p "$PREFIX"
install -m 0755 "$SCRIPT_DIR/bin/with-secrets" "$PREFIX/with-secrets"
say "installed: $PREFIX/with-secrets"

case ":$PATH:" in
*":$PREFIX:"*) ;;
*) say "WARNING: $PREFIX is not in PATH - add it in your shell profile" ;;
esac

# --- hook ---
mkdir -p "$HOOK_DIR"
install -m 0755 "$SCRIPT_DIR/hooks/guard-secrets.sh" "$HOOK_DIR/guard-secrets.sh"
say "installed: $HOOK_DIR/guard-secrets.sh"

# --- settings.json ---
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
jq -e . "$SETTINGS" >/dev/null || die "$SETTINGS is not valid JSON - fix it first"

backup="$SETTINGS.bak.$(date +%Y%m%d%H%M%S)"
cp "$SETTINGS" "$backup"

tmp="$(mktemp)"
jq --arg cmd "$HOOK_CMD" '
  .hooks //= {}
  | .hooks.PreToolUse //= []
  # drop a previous entry for this hook (idempotency)
  | .hooks.PreToolUse |= map(.hooks |= map(select(.command != $cmd)))
  # clean up matcher groups left empty by that
  | .hooks.PreToolUse |= map(select((.hooks | length) > 0))
  | .hooks.PreToolUse += [{
      matcher: "Bash",
      hooks: [{
        type: "command",
        command: $cmd,
        timeout: 10,
        statusMessage: "Secret guard"
      }]
    }]
' "$SETTINGS" > "$tmp"

jq -e . "$tmp" >/dev/null || { rm -f "$tmp"; die "merge produced invalid JSON, $SETTINGS left unchanged"; }
mv "$tmp" "$SETTINGS"
say "wired into: $SETTINGS (backup: $backup)"

say ""
say "Done. Restart Claude Code, or open /hooks once, so the settings reload."
say ""
say "Next step: hand prompts/SETUP.md to an agent."
