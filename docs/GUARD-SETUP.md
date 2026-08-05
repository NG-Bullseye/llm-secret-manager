# Setup prompt

Hand this to a coding agent (Claude Code or similar) inside the target project.
It is written as a checklist to execute, not a description to read.

---

Set up Keychain-based secret handling in this project. `with-secrets` and the
guard hook are already installed (via `install.sh` from keychain-secret-guard).

Work through the steps in order. Report the result of each step before moving on.

## 1. Inventory — without reading any values

- Find config files holding secrets: `.env`, `.env.local`, `*.secrets.*`, CI config.
- List key names only: `grep -oE '^[A-Za-z_]+=' <file>`.
  Do NOT open these files with cat/less/head. The guard hook blocks that, and it
  is right to.
- Check whether secrets are exported from my shell profile:
  `grep -nE '^export .*(SECRET|TOKEN|API_KEY|PASSWORD)' ~/.zshrc ~/.bashrc`
- Check whether those variables are set in this shell — using `${VAR:+set}` or
  `${#VAR}`. NEVER `${VAR:-...}` or `echo $VAR`; `:-` returns the value.

Report: which secrets exist, where they live, which are in cleartext.

## 2. Determine how the app reads its config

- Does it read `os.environ` / `process.env` directly? Then no code change is needed.
- Does it load a `.env` file through a loader (dotenv, python-decouple, ...)?
  Then migrated secrets must come from the process environment and must no longer
  appear in the file.
- Is there a container or compose start using `env_file`? That bypasses the
  wrapper. Report it explicitly even if it is not currently used.

## 3. Separate real secrets from ordinary config

Only real secrets belong in the Keychain. Things like `DEBUG`, `ALLOWED_ORIGINS`,
model names, dimensions and feature flags stay in `.env`.

Report your split before moving anything.

## 4. Order matters — this is the critical step

For each secret being migrated:

1. **First** remove the `export` from my shell profile.
   Reason: coding agents inherit the process environment of their shell. While
   the export exists, the value sits in every agent session — and a value rotated
   afterwards lands right back there.
2. **Then** rotate or store it.

Not the other way round.

## 5. Storing in the Keychain

Self-generatable secrets (a framework signing key, for example) you create
directly — generated and stored in one process so the value is never printed:

```python
import secrets, subprocess
key = secrets.token_urlsafe(50)
subprocess.run(["security", "add-generic-password", "-s", "<service>",
                "-a", "<account>", "-U", "-w", key], check=True)
```

Provider-issued material you cannot store without seeing it. I will enter that
myself. Give me the ready-to-run command:

```
security add-generic-password -s <service> -a <account> -U -w
```

`-w` as the last argument with no value — it prompts twice, and the value never
touches the command line, the shell history, or your context.

Do NOT store anything via `keyring.set_password()`: it makes the Python
interpreter the trusted principal of the Keychain ACL.

## 6. Build the start path

Create `scripts/dev` (or this project's equivalent) that starts the process
through `with-secrets`. Copy `with-secrets` into the repo as
`scripts/with-secrets` — a repo must not depend on a tool in a home directory.

No hardcoded paths. Derive them from `BASH_SOURCE`:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
```

## 7. Prove it works

- Start without the wrapper: must fail with a clear missing-variable error.
- Start with the wrapper: must run.
- `with-secrets --check VAR=service` shows length only.
- Verify the migrated variables are no longer set in a fresh shell, using
  `${VAR:+set}`.

Show me the output.

## 8. Summarise at the end

- What is now in the Keychain (service names, no values)
- What is still cleartext and why
- What I have to do myself: provider-side rotation, interactive storage, commits
- Which paths bypass the wrapper (compose, CI, production)

## Rules for the whole job

- Never run `security ... -w` directly.
- Never run `env`, `printenv`, `cat .env`.
- Existence checks only via `${VAR:+...}` or `${#VAR}`.
- If the guard hook blocks you, use the alternative named in the message. Do not
  reword the command to slip past the pattern.
- If you find a cleartext secret anywhere, report it immediately. Tidying it away
  does not invalidate a token — compromised material must be revoked at the
  provider.
