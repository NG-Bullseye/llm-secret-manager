#!/usr/bin/env bash
#
# Tests bin/bwv-redact.py with a synthetic value.
#
#   bash test/bwv-redact-test.sh
#
# Deliberately vault-free: the redaction path is the one piece of bwv that can
# be exercised without unlocking anything, and a test that needs a real secret
# to prove secrets stay hidden is a test nobody will run.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REDACT="$SCRIPT_DIR/../bin/bwv-redact.py"

[ -f "$REDACT" ] || { echo "missing: $REDACT" >&2; exit 1; }

SYNTH_VALUE="synthetic-value-0123456789-not-a-secret"
export SYNTH_VALUE
export BWV_REDACT_VARS="SYNTH_VALUE"

pass=0
fail=0

check() { # $1=label $2=expected $3=actual
	if [ "$2" = "$3" ]; then
		pass=$((pass + 1)); printf '  ok    %s\n' "$1"
	else
		fail=$((fail + 1)); printf '  FAIL  %s\n        expected=%s\n        got     =%s\n' "$1" "$2" "$3"
	fi
}

# The child echoes the injected value on both streams and exits non-zero.
child='printf "out:%s\n" "$SYNTH_VALUE"; printf "err:%s\n" "$SYNTH_VALUE" >&2; exit 3'

out="$(python3 "$REDACT" sh -c "$child" 2>/dev/null)"
rc_out=$?
err="$(python3 "$REDACT" sh -c "$child" 2>&1 >/dev/null)"

check "stdout is redacted"        "out:[REDACTED:SYNTH_VALUE]" "$out"
check "stderr is redacted"        "err:[REDACTED:SYNTH_VALUE]" "$err"
check "child exit code survives"  "3"                          "$rc_out"

# The value must not survive anywhere in the combined output.
combined="$out$err"
case "$combined" in
	*"$SYNTH_VALUE"*) leaked=yes ;;
	*)                leaked=no  ;;
esac
check "value does not leak" "no" "$leaked"

# An unset variable named in BWV_REDACT_VARS must not blow up or blank output.
BWV_REDACT_VARS="SYNTH_VALUE MISSING_VAR" \
	out2="$(python3 "$REDACT" sh -c 'printf "plain\n"' 2>/dev/null)"
check "unknown var is ignored" "plain" "$out2"

printf '\n%d ok, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
