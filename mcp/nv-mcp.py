#!/usr/bin/env python3
"""nv-mcp — MCP server for llm-secret-manager. Zero dependencies, Python >= 3.9.

Exposes the nv verbs as MCP tools so an LLM agent can operate the vault
without ever seeing a secret:

  secret_generate / secret_rotate  create secrets blind (only name+length back)
  secret_list / secret_delete      management, names only
  secret_run                       resolve references into the environment of
                                   a child process (HSM-call semantics) and
                                   REDACT any exact occurrence of the resolved
                                   values from the captured output

There is deliberately no secret_get. Nothing in this server returns secret
material to the client.

Transports:
  stdio (default)      newline-delimited JSON-RPC on stdin/stdout
  --http PORT          streamable-HTTP endpoint on http://127.0.0.1:PORT/mcp
                       (binds loopback only; meant to run as a LaunchAgent
                       inside the logged-in GUI session, where the login
                       keychain is available)
"""
import json
import os
import re
import subprocess
import sys

VERSION = "0.1.0"
NV_BIN = os.environ.get(
    "NV_BIN",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "nv"),
)
BWV_BIN = os.environ.get(
    "BWV_BIN",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "bwv"),
)
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Shared rules live here, not repeated in every tool description: this is sent
# once at initialize, while descriptions are carried in the model's context for
# the whole session.
INSTRUCTIONS = """secret_* = macOS keychain, bw_* = Bitwarden. No tool returns a value:
to use one, inject it with *_run; to verify one, check names or lengths.

bw refs are '<item>' or '<item>:<field>'; names must match EXACTLY (they hold
spaces and '·') -- call bw_list first. Default field: login password, else 'wert'.

New random value: bw_generate. A value that already exists elsewhere: have the
user run 'bwv import <item>' in a terminal (hidden prompt, no tool by design)."""

TOOLS = [
    {
        "name": "secret_generate",
        "description": "Create a keychain secret blind. Returns name and length only. Fails if the name exists; use secret_rotate instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "letters, digits, . _ -"},
                "length": {"type": "integer", "default": 32, "minimum": 8},
            },
            "required": ["name"],
        },
    },
    {
        "name": "secret_rotate",
        "description": "Overwrite a keychain secret with a fresh blind value.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "length": {"type": "integer", "default": 32, "minimum": 8},
            },
            "required": ["name"],
        },
    },
    {
        "name": "secret_list",
        "description": "List keychain secret names.",
        "inputSchema": {
            "type": "object",
            "properties": {"prefix": {"type": "string", "default": ""}},
        },
    },
    {
        "name": "secret_delete",
        "description": "Delete a keychain secret.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "secret_run",
        "description": "Run a command with keychain secrets in its environment. Output is redacted before it returns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "array", "items": {"type": "string"}, "description": "argv"},
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "VAR -> secret name",
                },
                "cwd": {"type": "string"},
                "timeout_s": {"type": "integer", "default": 120},
            },
            "required": ["command", "env"],
        },
    },
    {
        "name": "bw_list",
        "description": "List Bitwarden item names. Start here: references must match a name exactly.",
        "inputSchema": {
            "type": "object",
            "properties": {"prefix": {"type": "string", "default": ""}},
        },
    },
    {
        "name": "bw_check",
        "description": "Report each reference's value length. Confirms a reference resolves before you rely on it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "refs": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "VAR -> reference",
                },
            },
            "required": ["refs"],
        },
    },
    {
        "name": "bw_run",
        "description": "Run a command with Bitwarden values in its environment. Output is redacted before it returns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "array", "items": {"type": "string"}, "description": "argv"},
                "refs": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "VAR -> reference",
                },
                "cwd": {"type": "string"},
                "timeout_s": {"type": "integer", "default": 120},
            },
            "required": ["command", "refs"],
        },
    },
    {
        "name": "bw_generate",
        "description": "Create a random Bitwarden value blind. Returns name and length only. Overwrites the item if it exists, which is the rotation path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "reference; field defaults to 'wert'"},
                "length": {"type": "integer", "default": 32, "minimum": 8},
            },
            "required": ["item"],
        },
    },
    {
        "name": "bw_delete",
        "description": "Delete a Bitwarden item by exact name.",
        "inputSchema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
        },
    },
]


def nv(*args, timeout=30):
    p = subprocess.run(
        [NV_BIN, *args], capture_output=True, text=True, timeout=timeout
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def bwv(*args, timeout=120, cwd=None):
    """Invoke the Bitwarden backend. Only references travel on argv; the
    resolved values stay inside the bwv child and never reach this process."""
    p = subprocess.run(
        [BWV_BIN, *args], capture_output=True, text=True, timeout=timeout, cwd=cwd
    )
    return p.returncode, p.stdout, p.stderr


def bw_specs(refs):
    """Turn a {VAR: reference} mapping into bwv's VAR=<ref> argument list."""
    specs = []
    for var, ref in refs.items():
        if not VAR_RE.match(var):
            raise ValueError(f"invalid variable name '{var}'")
        if not isinstance(ref, str) or not ref:
            raise ValueError(f"invalid reference for '{var}'")
        specs.append(f"{var}={ref}")
    if not specs:
        raise ValueError("refs must not be empty")
    return specs


def resolve_secret(name):
    """Fetch one secret value from the native vault. The value stays inside
    this process; callers must only place it into a child's environment."""
    if not NAME_RE.match(name):
        raise ValueError(f"invalid secret name '{name}'")
    # Same resolution order as bin/with-secrets: prefer the item stored under
    # the current account, fall back to a service-only match. Existing items on
    # a machine were created with inconsistent accounts; a name is the contract,
    # not the account.
    attempts = (
        ["-a", os.environ.get("USER", ""), "-s", name],
        ["-s", name],
    )
    for sel in attempts:
        p = subprocess.run(
            ["security", "find-generic-password", *sel, "-w"],
            capture_output=True, text=True, timeout=30,
        )
        if p.returncode == 0:
            return p.stdout.rstrip("\n")
    raise ValueError(f"no secret named '{name}' (or keychain locked)")


def tool_call(name, args):
    if name in ("secret_generate", "secret_rotate"):
        sname = args["name"]
        if not NAME_RE.match(sname):
            raise ValueError(f"invalid secret name '{sname}'")
        length = int(args.get("length", 32))
        verb = "generate" if name == "secret_generate" else "rotate"
        code, out, err = nv(verb, sname, "-l", str(length))
        if code != 0:
            raise ValueError(err or out or f"nv {verb} failed")
        return {"ok": True, "name": sname, "length": length}

    if name == "secret_list":
        code, out, err = nv("list", *( [args["prefix"]] if args.get("prefix") else [] ))
        if code != 0:
            raise ValueError(err or "nv list failed")
        return {"names": out.splitlines()}

    if name == "secret_delete":
        sname = args["name"]
        if not NAME_RE.match(sname):
            raise ValueError(f"invalid secret name '{sname}'")
        code, out, err = nv("delete", sname)
        if code != 0:
            raise ValueError(err or "nv delete failed")
        return {"ok": True, "deleted": sname}

    if name == "secret_run":
        command = args["command"]
        if not isinstance(command, list) or not command:
            raise ValueError("command must be a non-empty argv array")
        mapping = args["env"]
        child_env = dict(os.environ)
        values = []
        for var, sname in mapping.items():
            if not VAR_RE.match(var):
                raise ValueError(f"invalid variable name '{var}'")
            value = resolve_secret(sname)
            child_env[var] = value
            values.append((var, value))
        p = subprocess.run(
            command,
            env=child_env,
            cwd=args.get("cwd") or None,
            capture_output=True,
            text=True,
            timeout=int(args.get("timeout_s", 120)),
        )
        out, err = p.stdout, p.stderr
        # Defense against accidental echo: exact matches of resolved values
        # never travel back to the client. (Encodings/derivations of a value
        # cannot be caught — see THREAT-MODEL.md.)
        for var, value in values:
            out = out.replace(value, f"[REDACTED:{var}]")
            err = err.replace(value, f"[REDACTED:{var}]")
        return {"exit_code": p.returncode, "stdout": out[-20000:], "stderr": err[-20000:]}

    if name == "bw_list":
        prefix = args.get("prefix") or ""
        code, out, err = bwv("list", *([prefix] if prefix else []))
        if code != 0:
            raise ValueError(err.strip() or "bwv list failed")
        return {"names": out.splitlines()}

    if name == "bw_check":
        specs = bw_specs(args["refs"])
        code, out, err = bwv("check", *specs)
        if code != 0:
            raise ValueError(err.strip() or "bwv check failed")
        # bwv prints "VAR: N chars" per reference; hand back structured data.
        lengths = {}
        for line in out.splitlines():
            var, _, rest = line.partition(":")
            lengths[var.strip()] = int(rest.strip().split()[0])
        return {"lengths": lengths}

    if name == "bw_run":
        command = args["command"]
        if not isinstance(command, list) or not command:
            raise ValueError("command must be a non-empty argv array")
        specs = bw_specs(args["refs"])
        # --redact is mandatory on this path: the server never holds the values,
        # so it cannot recognise them itself -- bwv, which does hold them,
        # filters the child's output before it ever comes back here.
        code, out, err = bwv(
            "run", "--redact", *specs, "--", *command,
            timeout=int(args.get("timeout_s", 120)),
            cwd=args.get("cwd") or None,
        )
        return {"exit_code": code, "stdout": out[-20000:], "stderr": err[-20000:]}

    if name == "bw_generate":
        item = args["item"]
        length = int(args.get("length", 32))
        code, out, err = bwv("generate", item, str(length))
        if code != 0:
            raise ValueError(err.strip() or "bwv generate failed")
        return {"ok": True, "item": item, "length": length}

    if name == "bw_delete":
        item = args["item"]
        code, out, err = bwv("delete", item)
        if code != 0:
            raise ValueError(err.strip() or "bwv delete failed")
        return {"ok": True, "deleted": item}

    raise ValueError(f"unknown tool '{name}'")


# --- JSON-RPC / MCP plumbing -------------------------------------------------

def handle(msg):
    """Returns a response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return None
    method = msg.get("method")
    msg_id = msg.get("id")
    if method is None:
        return None  # a response object; nothing to do
    if msg_id is None:
        return None  # notification (e.g. notifications/initialized)

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def rpc_error(code, text):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        client_version = (msg.get("params") or {}).get("protocolVersion", "2025-03-26")
        return ok({
            "protocolVersion": client_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "llm-secret-manager", "version": VERSION},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = tool_call(params.get("name", ""), params.get("arguments") or {})
            return ok({
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": False,
            })
        except subprocess.TimeoutExpired:
            return ok({"content": [{"type": "text", "text": "timeout"}], "isError": True})
        except (ValueError, KeyError, OSError) as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
    return rpc_error(-32601, f"method not found: {method}")


def serve_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def serve_http(port):
    # ThreadingHTTPServer, not HTTPServer: MCP clients keep the first
    # connection alive, and a single-threaded server would block every
    # further connection behind it (tools/list would just time out).
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # no request logging: URLs/bodies stay out of logs
            pass

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path.rstrip("/") not in ("/mcp", ""):
                return self._send(404, b'{"error":"not found"}')
            try:
                length = int(self.headers.get("Content-Length", "0"))
                msg = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send(400, b'{"error":"bad json"}')
            resp = handle(msg)
            if resp is None:
                return self._send(202)
            return self._send(200, json.dumps(resp, ensure_ascii=False).encode())

        def do_GET(self):
            # No server-initiated stream: this server only answers requests.
            self._send(405, b'{"error":"POST JSON-RPC to /mcp"}')

        def do_DELETE(self):
            self._send(200)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.serve_forever()


def main():
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1])
        serve_http(port)
    else:
        serve_stdio()


if __name__ == "__main__":
    main()
