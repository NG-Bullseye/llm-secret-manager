#!/usr/bin/env bash
#
# PreToolUse hook (matcher: Bash) for Claude Code.
#
# Blocks Bash commands that would write a secret value into the agent's context.
# Runs even in bypassPermissions mode: PreToolUse fires before the permission
# check, so a "deny" still applies there.
#
# Deliberately still allowed: anything that only INJECTS secrets without
# printing them (with-secrets), and existence checks via ${#VAR} / ${VAR:+...}.
#
# Exit 0 plus JSON on stdout drives the decision.

set -uo pipefail

# Without jq the hook could not inspect anything and would silently allow
# everything. That is an unnoticed total loss of protection, so make it visible.
if ! command -v jq >/dev/null 2>&1; then
	printf '%s\n' '{"systemMessage":"Secret guard INACTIVE: jq is missing, commands are not being checked (brew install jq)."}'
	exit 0
fi

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)"

[ -n "$cmd" ] || { echo '{}'; exit 0; }

deny() {
	jq -n --arg r "$1" '{
		hookSpecificOutput: {
			hookEventName: "PreToolUse",
			permissionDecision: "deny",
			permissionDecisionReason: $r
		}
	}'
	exit 0
}

# Name fragments that suggest a secret.
SECRETISH='SECRET|TOKEN|API_KEY|APIKEY|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_KEY'

# 1) Cleartext Keychain read. -w prints the password and nothing else.
#    with-secrets calls this internally, but never via a visible Bash command.
if printf '%s' "$cmd" | grep -Eq 'security[[:space:]]+find-(generic|internet)-password[^|;&]*(^|[[:space:]])-w([[:space:]]|$)'; then
	deny "Cleartext Keychain read. Use 'with-secrets VAR=service -- <cmd>' to inject, or 'with-secrets --check VAR=service' to verify."
fi

# 2) Keychain read through an interpreter.
if printf '%s' "$cmd" | grep -Eq 'keyring\.get_password|get_generic_password|SecKeychainFindGenericPassword'; then
	deny "Keychain read via interpreter. Use 'with-secrets' instead of reading the value."
fi

# 3) Full environment dump. 'env -u X cmd' and 'env -i cmd' stay allowed
#    because they set the environment rather than printing it.
if printf '%s' "$cmd" | grep -Eq '(^|[;&|][[:space:]]*)(env|printenv)([[:space:]]*$|[[:space:]]*\|)'; then
	deny "An environment dump would write every set secret into the context. Check individually with \${#VAR} (length) instead of env."
fi

# 4) Printing a secret-looking variable.
#    Also catches ${VAR:-...}, because ':-' yields the VALUE when set.
#    The safe forms ${#VAR} (length) and ${VAR:+text} (existence) are stripped
#    first so they do not trigger a false block.
probe="$(printf '%s' "$cmd" | sed -E \
	-e 's/\$\{#[A-Za-z_][A-Za-z0-9_]*\}//g' \
	-e 's/\$\{[A-Za-z_][A-Za-z0-9_]*:\+[^}]*\}//g')"

if printf '%s' "$probe" | grep -Eq '(echo|printf|print)[^|;&]*\$\{?[A-Za-z_]*('"$SECRETISH"')' ; then
	deny "Printing a secret variable. Use \${VAR:+set} or \${#VAR} for existence checks, never \${VAR:-...} (which yields the value)."
fi

# 5) Displaying .env files.
if printf '%s' "$cmd" | grep -Eq '(cat|bat|less|more|head|tail|open)[[:space:]][^|;&]*\.env([[:space:]]|$|\.|/)'; then
	deny "Displaying a .env file. For structure without values: grep -oE '^[A-Za-z_]+=' <file>"
fi

echo '{}'
exit 0
