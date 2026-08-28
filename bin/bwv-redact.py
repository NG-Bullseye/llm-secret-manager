#!/usr/bin/env python3
"""bwv-redact — run a child and strip resolved secret values from its output.

Used by `bwv run --redact` on the machine-caller path (MCP server), where the
child's output travels back into an agent transcript and must not carry a
secret with it. BWV_REDACT_VARS names the environment variables holding
resolved values; every exact occurrence of one is replaced by [REDACTED:VAR].

Capturing here rather than in bash is deliberate: the shell alternative is
redirecting to temp files, which would put a printed secret on disk — the one
outcome this tool exists to prevent.

Exact matches only. A child that re-encodes the value (base64, hex, chunked)
defeats this; see docs/THREAT-MODEL.md, "a hostile agent instructing a child
to exfiltrate". This is a guard against accidental echo, not a sandbox.
"""
import os
import subprocess
import sys


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("bwv-redact: no command given\n")
        return 64
    p = subprocess.run(sys.argv[1:], capture_output=True, text=True)
    out, err = p.stdout, p.stderr
    for var in os.environ.get("BWV_REDACT_VARS", "").split():
        value = os.environ.get(var)
        # A one-character value would redact almost everything; a length floor
        # keeps a misconfigured reference from mangling unrelated output.
        if value and len(value) >= 4:
            marker = "[REDACTED:%s]" % var
            out = out.replace(value, marker)
            err = err.replace(value, marker)
    sys.stdout.write(out)
    sys.stderr.write(err)
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
