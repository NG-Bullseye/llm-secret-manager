#!/usr/bin/env python3
"""bwv-import — store a value into a Bitwarden item without it passing through
argv, a file, or the terminal echo.

Two entry points, for two different origins of the value:

  <item>[:<field>]                 `bwv import` — the value exists elsewhere
                                   (a provider's web UI) and a human types it.
                                   Hidden prompt, twice, and they must match.
                                   Needs a TTY: a pipe would mean the value
                                   came from a file, an argument or a chat.

  --generate <length> <item>[:...] `bwv generate` — nothing to type. The value
                                   is drawn from os.urandom here and goes
                                   straight into the vault. No TTY, because no
                                   human is involved; this is the path an agent
                                   uses through the MCP server.

Called inside the unlocked child, so BW_SESSION is already in the environment.
The value is handed to `bw` on stdin via `bw encode`, never on argv.

Creates a secure note when the item does not exist yet and updates it in place
when it does — rotation is the common case, and an agent that has to delete and
recreate an item loses its folder and history.

Prints the stored length and nothing else. There is no read-back verb here for
the same reason bin/nv has none.
"""
import getpass
import json
import os
import secrets
import subprocess
import sys

DEFAULT_FIELD = "wert"
SECURE_NOTE = 2  # bitwarden item type
FIELD_HIDDEN = 1  # custom field type: hidden
# Same alphabet as bin/nv: no quote, backslash, $ or backtick, so a generated
# value cannot break out of a shell string it is later interpolated into.
CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#%^&*()_+=-"


def bw(*args, stdin=None):
    p = subprocess.run(
        ["bw", *args], input=stdin, capture_output=True, text=True, timeout=60
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or f"bw {args[0]} failed")
    return p.stdout


def find_item(name):
    """Exact-name lookup. `bw get item` matches substrings and would resolve an
    ambiguous name to the wrong item, so filter the list ourselves."""
    items = json.loads(bw("list", "items", "--search", name) or "[]")
    exact = [i for i in items if i.get("name") == name]
    if len(exact) > 1:
        raise RuntimeError(f"{len(exact)} items named {name!r}")
    return exact[0] if exact else None


def read_value(name, field):
    if not sys.stdin.isatty():
        raise RuntimeError(
            "import needs an interactive terminal (hidden prompt); "
            "a secret must not arrive through a pipe or an argument"
        )
    first = getpass.getpass(f"value for {name} [{field}]: ")
    if not first:
        raise RuntimeError("empty value")
    if first != getpass.getpass("repeat: "):
        raise RuntimeError("values do not match")
    return first


def set_field(item, field, value):
    """Put the value where bwv's resolver will look for it."""
    if field == "password":
        item.setdefault("login", {})["password"] = value
        return
    if field == "username":
        item.setdefault("login", {})["username"] = value
        return
    fields = item.get("fields") or []
    for existing in fields:
        if existing.get("name") == field:
            existing["value"] = value
            break
    else:
        fields.append({"name": field, "value": value, "type": FIELD_HIDDEN})
    item["fields"] = fields


def main():
    argv = sys.argv[1:]
    length = None
    if argv[:1] == ["--generate"]:
        if len(argv) != 3:
            sys.stderr.write("usage: bwv-import.py --generate <length> <item>[:<field>]\n")
            return 64
        length = int(argv[1])
        if length < 8:
            raise RuntimeError("length must be >= 8")
        argv = argv[2:]
    if len(argv) != 1:
        sys.stderr.write("usage: bwv-import.py [--generate <length>] <item>[:<field>]\n")
        return 64

    ref = argv[0]
    name, sep, field = ref.rpartition(":")
    if not sep:
        name, field = ref, DEFAULT_FIELD

    existing = find_item(name)
    if length is None:
        value = read_value(name, field)
    else:
        # Blind: generated here, written straight to the vault. The caller that
        # ordered it gets back name and length, nothing else.
        value = "".join(secrets.choice(CHARSET) for _ in range(length))

    if existing:
        set_field(existing, field, value)
        payload = bw("encode", stdin=json.dumps(existing))
        bw("edit", "item", existing["id"], stdin=payload)
        action = "updated"
    else:
        item = json.loads(bw("get", "template", "item"))
        item["type"] = SECURE_NOTE
        item["name"] = name
        item["notes"] = None
        item["secureNote"] = {"type": 0}
        item["login"] = None
        item["fields"] = []
        set_field(item, field, value)
        payload = bw("encode", stdin=json.dumps(item))
        bw("create", "item", stdin=payload)
        action = "created"

    print(f"bwv: {name!r} {action}, field {field!r}, length {len(value)}. "
          "The value was not displayed and cannot be read back through bwv.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"bwv-import: {exc}\n")
        sys.exit(1)
