# MemoryForge

Local memory for coding agents. OpenCode, Cursor, Claude Code, and any other MCP client read and write the same short facts. The data is one SQLite file on your machine. A language model is optional, and search never calls one.

The notebook UI is in English by default; German is a switch in **Settings**. [Deutsche Anleitung](README.de.md).

## What it stores

Short facts that should still be true next week: a preference, a decision, a convention, a lesson from a bug. Not chat logs, not the current task, not secrets.

The file layout follows OpenClaw and Claude Code:

| Layer | File | Search |
|---|---|---|
| Identity | `IDENTITY.md` | name, vibe, mark. Evergreen. Not a fact. |
| Voice | `SOUL.md` | tone and boundaries. Project wins over global. |
| Profile | `USER.md` | evergreen preferences, written as directives |
| Durable | `MEMORY.md` | evergreen facts, decisions, conventions, lessons |
| Daily | `memory/YYYY-MM-DD.md` | working notes, 30-day half-life |
| Review | `DREAMS.md` | dream diary, not searched, not injected |

SQLite stays the source of truth. The Markdown vault is a projection under the data directory, rewritten when a memory changes. Editing a file does not change memory.

Each fact has a scope.

| Scope | Means |
|---|---|
| `global` | about you, in every repo |
| `project:host/owner/repo` | about that repository |

A project search also returns `global`. A global search does not return project facts. Writing, replacing, and dreaming stay inside one scope, so a repo fact cannot overwrite a preference.

If you omit the scope, the CLI and a stdio MCP session run `git remote get-url origin` in the working directory.

| Remote | Scope |
|---|---|
| `git@github.com:owner/repo.git` | `project:github.com/owner/repo` |
| `https://github.com/owner/repo.git` | same |
| no git, or no `origin` | `global` |

The HTTP server cannot see your repo. Pass `scope` yourself. It binds to `127.0.0.1` unless you change that.

## What it does not do

No account, no hosted vector database. Search and embeddings stay local. Strings that look like secrets (`api_key=…`, `sk-…`, `ghp_…`, private keys) are redacted before they are stored. Do not put secrets in memory anyway.

Dreaming does not invent facts. With the model off, it changes nothing. With the model on, a sweep has three phases: light (stage near-duplicates), REM (a review sentence, marked as reflection), and deep (merge duplicates, promote a qualified daily note verbatim into `MEMORY.md` or `USER.md`). The diary lands in `DREAMS.md`.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Git, if you want project scopes detected for you
- optional: an API key for DeepSeek, OpenCode Go, or another OpenAI-compatible API

The first real embedding downloads `BAAI/bge-small-en-v1.5` into the local cache. Without `fastembed`, search still works, using a hash embedder plus full text. That mode is for tests and for machines where the model download is not wanted. Recall is weaker.

## Install

```bash
git clone https://github.com/pierelucas/MemoryForge.git
cd MemoryForge
./install.sh
```

The script installs `uv` if it is missing, then installs the `memoryforge` command. In a terminal it asks whether to configure a model now. `--yes` skips the questions.

```bash
./install.sh --yes --service
```

`--service` installs a user service: systemd on Linux, launchd on macOS. On Windows, run `memoryforge serve` in the foreground. The service starts at login. To keep it running without a login, run `loginctl enable-linger "$USER"` once.

| | |
|---|---|
| Config | `~/.config/memoryforge/config.toml` (mode `0600`) |
| Database | `~/.local/share/memoryforge/memory.db` |
| Vault | `~/.local/share/memoryforge/vault/` |
| Service log | `~/.local/share/memoryforge/serve.log` |

`XDG_CONFIG_HOME` and `XDG_DATA_HOME` replace those roots.

## Notebook

```bash
memoryforge            # start the server if it is down, print the URL
memoryforge ui         # open the notebook
memoryforge serve      # foreground
memoryforge serve --detach
memoryforge stop
memoryforge doctor
```

Default URL: <http://127.0.0.1:4737/>

The sidebar is the scope list. **All** shows everything. **Global** shows only global facts. **Persona** is the voice for that scope. Layer tabs split durable facts, daily notes, and the dream diary. **Files** shows the Markdown projection; editing it does not write back. A repository shows that repository, and underneath the global facts an agent would also see there. Search in a repository searches both. **Delete scope** on a scope page hides every active fact in it after a confirmation page. The rows stay in the file, and **All** is a view, not a scope, so it has no delete link.

**Remember** stores one fact in the scope selected above the button. **Other scope** is for a scope that does not exist yet. A git URL in that field is normalized. `/` focuses search. Ctrl+Enter or Cmd+Enter submits the note you are typing.

**Pin** keeps a fact on the session card (`memory_brief`). **Forget** hides a fact from search, the list, and MCP. The row stays in the file. **Edit** replaces the text and refreshes the embedding, and its scope select moves the fact to another scope or to a new name. A move into a scope that already holds the same text is rejected. The form does not set a kind. With the model off, UI notes are stored as `fact`. With the model on, a longer note may be split or classified.

**Settings** holds the AI options, the language (English or German), the check and dream buttons, and the backup download with and without the key.

`autostart` in the config only records the wish. Login startup comes from `memoryforge install-service` or `./install.sh --service`.

## Model

Off is the default. `add` then stores the text as written, unless that exact text already exists in the scope.

On: one short sentence with no close neighbor is still stored as written. Longer notes, and notes that sit next to a similar fact, go to the model. If the API fails, the original text is stored anyway.

Search does not call the API.

The provider list includes DeepSeek, OpenCode Go, OpenAI, OpenRouter, xAI, Groq, Mistral, Gemini, Cerebras, Together, Fireworks, Moonshot, DashScope, GitHub Models, Hugging Face, NVIDIA, Ollama, LM Studio, and any other OpenAI-compatible API.

Choosing a provider fills the API base. If a key is already stored, or you paste one, the model menu loads that provider's ids. OpenCode Go and OpenRouter publish their catalogs, so those load without a key. Ollama and LM Studio need no key. A filled custom id still wins. `memoryforge config set llm.provider openai` also replaces a default base URL; a URL you typed yourself stays.

```bash
memoryforge config models
memoryforge config models --live
memoryforge config set llm.enabled true
memoryforge config set llm.provider opencode-go
memoryforge config set llm.model glm-5.3-flash
memoryforge config set llm.api_key sk-...
memoryforge config set llm.thinking false
memoryforge config set ui.lang de
memoryforge config show
```

`config show` masks the key. Leave thinking off for extraction.

The embedding model is not this menu. It stays `BAAI/bge-small-en-v1.5` on disk. Changing the chat model does not touch old vectors. Changing the embedding model does: run `memoryforge reembed` afterwards.

```bash
memoryforge dream
memoryforge dream --scope global
memoryforge note "Heute den Port geprüft."
memoryforge vault
```

`note` writes a daily note and does not call the model. `vault` rewrites the Markdown projection. `memoryforge restore` rewrites it too, so an old vault cannot outlive the restored database.

## CLI

```bash
memoryforge persona set soul "Be precise. No filler." --scope global
memoryforge note "Heute den Port geprüft."
memoryforge add "Bevorzuge pnpm statt npm."
memoryforge add --scope global "Antworten dürfen Deutsch sein."
memoryforge add --scope project:github.com/pierelucas/MemoryForge "Port der UI ist 4737."
echo "ein Fakt" | memoryforge add -
memoryforge search "package manager"
memoryforge search "port" --scope global
memoryforge list
memoryforge list --scope global
memoryforge pin <id>
memoryforge pin <id> --off
memoryforge forget <id>
memoryforge export -o memories.json
memoryforge import memories.json
memoryforge doctor
```

## OpenCode

stdio is the one to use. OpenCode starts the process in the project directory, MemoryForge reads `origin`, and both sides use the same database as the notebook.

`~/.config/opencode/opencode.json` (OpenCode 2), or the project config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "memoryforge": {
        "type": "local",
        "command": ["memoryforge", "mcp"]
      }
    }
  }
}
```

Older configs, without `servers`:

```json
{
  "mcp": {
    "memoryforge": {
      "type": "local",
      "command": ["memoryforge", "mcp"],
      "enabled": true
    }
  }
}
```

The tools do nothing if the agent never calls them. Put this in the project instructions:

```text
At session start call memory_brief and read card first. Pass scope project:<host/owner/repo> when you know the git remote, otherwise omit it.
Call memory_persona_set when the user states a name, vibe, or voice. Global applies everywhere. Project wins on conflict.
When you learn a durable preference, decision, convention, or debug lesson, call memory_add with one or a few sentences.
Call memory_note for a working note that should not enter MEMORY.md until dreaming promotes it.
When a stored fact changed and you know its id, call memory_update instead of adding a second copy.
Do not store secrets, tokens, or ephemeral task state.
```

| Tool | Use |
|---|---|
| `memory_brief` | session start: read `card` first. Persona, directives, standing facts, recent notes |
| `memory_persona_set` | set `identity` or `soul` for a scope. Empty text clears it |
| `memory_search` | meaning plus full text |
| `memory_add` | store a durable fact |
| `memory_note` | store a daily note; dreaming may promote it later |
| `memory_update` | replace the text of one row, or move it |
| `memory_list` | active rows |
| `memory_pin` | pin or unpin |
| `memory_forget` | hide a row |

Cursor, Claude Code, and other clients on this machine can use the same stdio command. A client that cannot start a process uses HTTP, after `memoryforge` is running:

```text
http://127.0.0.1:4737/mcp
```

There is no authentication on that port. Do not bind it to a shared network. On the default loopback bind the notebook rejects requests with a foreign `Host` header and form posts from another origin. `curl` and MCP clients that send no origin still work.

## Config

```toml
[server]
autostart = false
host = "127.0.0.1"
port = 4737
open_browser = false

[llm]
enabled = false
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = "deepseek-flash"
thinking = false
api_key = ""

[embed]
model = "BAAI/bge-small-en-v1.5"

[ui]
lang = "en"
```

`memoryforge config set section.field value`. Booleans: `true`, `false`, `ja`, `nein`, `an`, `aus`. `ui.lang` takes `en` or `de`; a missing or unknown value falls back to English.

## Move to another machine

```bash
memoryforge backup
memoryforge backup --without-secrets -o ~/merk.zip
```

The zip contains three files, nothing else:

```text
manifest.json    format version, time, embedding model
config.toml      includes the API key, unless you passed --without-secrets
memory.db        SQLite backup, not a live WAL
```

The program, the model cache, and logs are not in the zip. The key is plaintext in the archive, so you do not have to type it again. Do not send that file around. `--without-secrets` blanks the key.

On the new machine, from a fresh clone:

```bash
./install.sh --restore memoryforge-backup-20261019-1504.zip
```

If the command is already installed:

```bash
memoryforge restore memoryforge-backup-20261019-1504.zip
memoryforge
```

Restore stops a running server first. Files land in the usual directories on **this** machine. Old home paths are not copied. If the embedding model in the manifest does not match the local config, restore says so. Run `memoryforge reembed`.

A zip with extra paths or `..` is rejected. So is a format version this build does not know. Both checks happen before anything is overwritten.

The notebook can download the same zip from **Settings** under **Move**: one button with the key, one without.

## Uninstall

```bash
./uninstall.sh            # remove the service and command, keep the data
./uninstall.sh --purge    # also remove config and database
```

The script stops the service, disables the systemd unit, removes the macOS LaunchAgent, and uninstalls the command. It leaves `uv` installed. The OpenCode configuration is not touched; remove the `memoryforge` entry there or under `/mcps`.

By hand:

```bash
memoryforge stop
uv tool uninstall memoryforge
rm -rf ~/.config/memoryforge ~/.local/share/memoryforge
```

On Linux, also `systemctl --user disable --now memoryforge` and delete `~/.config/systemd/user/memoryforge.service`. On macOS, `launchctl unload` the agent `~/Library/LaunchAgents/com.memoryforge.plist`.

## Development

```bash
uv venv
uv pip install -e ".[dev]"
pytest
memoryforge serve
```

Tests force the hash embedder (`MEMORYFORGE_EMBED=hash`) and do not touch your real database.

## License

MIT. See [LICENSE](LICENSE).
