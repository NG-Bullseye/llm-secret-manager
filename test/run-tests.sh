#!/usr/bin/env bash
#
# Tests hooks/guard-secrets.sh against test/cases.tsv.
#
#   bash test/run-tests.sh
#
# The cases live in a data file rather than in this script on purpose: when the
# script is started through a Bash tool under an active guard hook, literal test
# patterns in the command text would block the invocation itself.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="${1:-$SCRIPT_DIR/../hooks/guard-secrets.sh}"
CASES="$SCRIPT_DIR/cases.tsv"

[ -x "$HOOK" ] || { echo "hook not executable: $HOOK" >&2; exit 1; }
[ -f "$CASES" ] || { echo "cases file missing: $CASES" >&2; exit 1; }

pass=0
fail=0

while IFS="$(printf '\t')" read -r expected cmd; do
	[ -n "${expected:-}" ] || continue
	case "$expected" in \#*) continue ;; esac

	actual="$(jq -n --arg c "$cmd" '{tool_name:"Bash",tool_input:{command:$c}}' \
		| "$HOOK" \
		| jq -r '.hookSpecificOutput.permissionDecision // "allow"')"

	if [ "$actual" = "$expected" ]; then
		pass=$((pass + 1))
		printf '  ok    %-6s %s\n' "$actual" "$cmd"
	else
		fail=$((fail + 1))
		printf '  FAIL  expected=%s got=%s  %s\n' "$expected" "$actual" "$cmd"
	fi
done < "$CASES"

printf '\n%d ok, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
