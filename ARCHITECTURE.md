# ARCHITECTURE — llm-secret-manager

## Deep Modules — Agent bestellt, rotiert und nutzt Secrets, liest sie nie

Flow: ein Agent ruft `nv`/`bwv` direkt oder über den MCP-Server `mcp/nv-mcp.py`; Secrets bleiben Referenzen (`VAR=name`) und werden erst beim `run` in die Umgebung des Zielprozesses aufgelöst. Der guard hook blockt Befehle, die einen Wert ausgeben würden. Keine Flow-Datei; die Sequenz lebt in `mcp/nv-mcp.py::tool_call`. Jede Innenleben-Zelle ist datei:zeile und muss per grep -n treffen.

## Flow

**Sequenz**

| # | Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|---|
| 1 | MCP | JSON-RPC (stdio oder `--http PORT` loopback) | Tool-Ergebnis ohne Secret | — | Transport | mcp/nv-mcp.py:232 `def tool_call` |
| 2 | nv (Keychain) | Unterbefehl + Name | stored/length, exit code | GUI-Session entsperrt | `-l N` | bin/nv:144 `generate)` |
| 3 | bwv (Bitwarden) | Unterbefehl + `item[:field]` | Namen, Längen, exit code | Master-Passwort per `with-secrets` | `BWV_BOOTSTRAP` | bin/bwv:65 `bw unlock` |
| 4 | Injection | Referenzen `VAR=name` | `exec` des Zielprozesses mit env | — | `--redact` | bin/nv:121 `exec` |

**Parallel**

| Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|
| guard hook | Bash-Befehl (PreToolUse) | deny bei Ausgabe eines Secrets | Claude Code hook aktiv | Muster | hooks/guard-secrets.sh:28 `deny()` |
| redact | Prozess-Output | Output mit REDACTED | `bw_run` | — | bin/bwv-redact.py:22 `def main` |

## Schnittstellen

- MCP-Tools: fünf `secret_*` (Keychain) + fünf `bw_*` (Bitwarden), bewusst kein `secret_get` (mcp/nv-mcp.py:14 `no secret_get`).
- macOS LaunchAgent-Vorlage `launchd/com.llm-secret-manager.mcp.plist.template`; Installation `install.sh`.
- Tests: `test/run-tests.sh`.

## Standard: Deep Modules + Flow

Standard R1–R5 steht in `~/repos/speech-engine/ARCHITECTURE.md`.
