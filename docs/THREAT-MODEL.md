# Threat model

## Actors

- **Operator (human):** owns the OS user session and the vault. Can see
  secrets through the OS vault UI — that is the intended escape hatch.
- **Agent (LLM):** orders operations (generate, rotate, run) via CLI or MCP.
  Everything the agent sees — tool results, logs, transcripts — is assumed to
  be *persisted and potentially exfiltrated*. The design goal is that secret
  values never appear there.
- **Target process:** the program that legitimately needs the secret at
  runtime. It receives the value via its environment and is trusted with it.

## Guarantees

1. **No cleartext in the agent path.** No verb returns secret material.
   Generation returns name + length; `secret_run` returns exit code and
   output with exact matches of every resolved value redacted.
2. **No cleartext at rest outside the vault.** Values are never written to
   files, argv (visible via `ps`), shell history, or logs. Writes to the
   keychain go through stdin (`security -i`), not arguments.
3. **Native access control.** Storage, locking, and session binding are the
   OS vault's own (macOS: login keychain, unlocked GUI sessions only). This
   tool adds no parallel storage and no custom crypto that could weaken it.
4. **Blind generation.** The value is created from `/dev/urandom` in a local
   subprocess and goes directly into the vault. The ordering agent never
   holds it.

## Non-goals / accepted residual risks

- **Same-user privilege separation.** Any process running as the same user in
  an unlocked session can call the same OS APIs. The OS vault model does not
  distinguish "the LLM's shell" from "your shell". What you get is leak
  prevention plus a single, auditable choke point — not a permission boundary.
  If you need per-use human approval, put the vault item behind user-presence
  (e.g. Touch ID-protected items) — the native mechanisms compose with nv.
- **A hostile agent instructing a child to exfiltrate.** `secret_run` executes
  a command the agent chose; that command could re-encode the secret (base64,
  etc.) and print it, bypassing exact-match redaction. Mitigations: the choke
  point makes such behavior visible and greppable; the PreToolUse guard hook
  (`hooks/guard-secrets.sh`) denies the common print paths before they run;
  restrict which commands the agent may run at your agent-framework layer if
  this is in your threat model.
- **In-memory exposure at use time.** The resolving process and the target
  process hold the value in RAM while running. No software vault — hardware
  HSMs included — can hand a usable secret to a process without that process
  having it in memory.
- **Loopback trust.** The HTTP transport binds 127.0.0.1 and adds no
  authentication: anything that can reach your loopback as your user is, per
  the same-user assumption above, already inside the boundary. Do not port-
  forward it beyond machines you trust; the SSH tunnel inherits SSH's auth.

## Design consequences

- The MCP server runs as a **LaunchAgent in the logged-in GUI session** —
  when you log out, the vault seals and the server loses access. Native
  semantics are the feature; nothing is re-implemented, so nothing can drift.
- Adding backends (Linux `secret-tool`, Windows Credential Manager) must
  preserve invariants 1–4 or not be added at all.
