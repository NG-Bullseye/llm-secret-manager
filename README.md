# native-vault

**Let an LLM agent manage your secrets without ever being able to read them.**

`native-vault` is a deliberately thin wrapper around the **OS-native keyvault**
(macOS Keychain) plus a zero-dependency **MCP server**, so that AI agents can
create, rotate, and *use* secrets — while the secret values never enter the
agent's context, its logs, or its transcripts.

You don't have to trust this code with your secrets, because it doesn't hold
any: storage and access control stay entirely with the operating system's own
vault. The whole tool is a few hundred lines of shell and Python you can audit
in one sitting. No dependencies, no custom crypto, no storage format.

## The model: the agent is an HSM operator, not a key holder

1. **Blind generation.** `nv generate api-token` creates the value in a local
   subprocess and writes it straight into the native vault. What comes back is
   `stored (length 32)` — nothing else. The agent that *ordered* the secret has
   never seen it.
2. **No `get` verb — by design.** There is no command and no MCP tool that
   returns a secret in cleartext. Not for the agent, not for a log line, not
   "just for debugging". The only escape hatch is the OS vault UI
   (Keychain Access), which is yours, not the agent's.
3. **Reads resolve only at injection time.** Everywhere else, secrets exist
   only as *references* (`DB_PASSWORD=api-token`). `nv run` resolves the
   reference at the last possible moment — like an HSM call — directly into
   the environment of the target process:

   ```bash
   nv run DB_PASSWORD=api-token -- python manage.py migrate
   ```

   The value never touches disk, logs, shell history, or `ps` output (argv
   carries only the reference). When the process exits, the value is gone.

## Quickstart (macOS)

```bash
git clone https://github.com/NG-Bullseye/native-vault && cd native-vault
sudo ln -s "$PWD/bin/nv" /usr/local/bin/nv   # or add bin/ to PATH

nv generate my-api-key            # blind: value is created and stored, never shown
nv run API_KEY=my-api-key -- ./deploy.sh
nv list my-                       # names only
nv rotate my-api-key              # fresh value, same reference
nv import legacy-password         # hidden interactive prompt (for existing secrets)
nv delete my-api-key
```

The macOS Keychain's native rules apply unchanged: the login keychain is only
available inside an **unlocked GUI session**. Over plain SSH, writes and reads
fail — that is Apple's access model doing its job, and the reason the MCP
server below runs as a LaunchAgent *inside* your session.

## MCP server

`mcp/nv-mcp.py` (Python ≥ 3.9, stdlib only) exposes the same verbs as MCP
tools: `secret_generate`, `secret_rotate`, `secret_list`, `secret_delete`,
`secret_run`. Secret values are resolved inside the server process and placed
into the child's environment; any **exact occurrence of a resolved value in
the captured output is redacted** before the result goes back to the client.

Run inside your GUI session (recommended — this is what makes the keychain
reachable for agents):

```bash
scripts/install-launchagent.sh          # starts http://127.0.0.1:8765/mcp
```

Register with your agent, e.g. Claude Code:

```bash
claude mcp add --transport http native-vault http://127.0.0.1:8765/mcp
```

Remote agents (e.g. a headless box you trust) can reach it through an SSH
tunnel — the server itself binds loopback only:

```bash
ssh -N -L 8765:127.0.0.1:8765 your-mac &
claude mcp add --transport http native-vault http://127.0.0.1:8765/mcp
```

Stdio transport is also available (`python3 mcp/nv-mcp.py`), useful when the
agent itself runs inside the GUI session.

## What this protects against — and what it doesn't

Honest scope (details in [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md)):

- **Protects:** secrets leaking into LLM context/transcripts, logs, shell
  history, process argv, files on disk, accidental echo (exact-match
  redaction). Vault semantics (locking, GUI binding) remain the OS's.
- **Does not protect:** processes running as the *same user* in an unlocked
  session are equal in the eyes of the OS — this is leak prevention and
  auditability, not privilege separation. A target process handed a secret
  via `secret_run` can still do with it what it wants; at generation time the
  value exists briefly in the generating subprocess's memory (as in any
  system, including an HSM's caller).

## License

MIT
