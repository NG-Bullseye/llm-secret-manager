#!/usr/bin/env bash
#
# Testet hooks/guard-secrets.sh gegen test/cases.tsv.
#
#   bash test/run-tests.sh
#
# Die Testfaelle stehen bewusst in einer Datendatei und nicht im Script:
# wenn dieses Script unter einem aktiven Guard-Hook per Bash-Tool gestartet
# wird, wuerden literale Testmuster im Kommandotext den Aufruf selbst blocken.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="${1:-$SCRIPT_DIR/../hooks/guard-secrets.sh}"
CASES="$SCRIPT_DIR/cases.tsv"

[ -x "$HOOK" ] || { echo "hook nicht ausfuehrbar: $HOOK" >&2; exit 1; }
[ -f "$CASES" ] || { echo "cases fehlen: $CASES" >&2; exit 1; }

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
		printf '  FAIL  erwartet=%s bekam=%s  %s\n' "$expected" "$actual" "$cmd"
	fi
done < "$CASES"

printf '\n%d ok, %d fehlgeschlagen\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
