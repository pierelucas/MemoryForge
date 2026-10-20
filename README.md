# MemoryForge

Local memory for coding agents. OpenCode, Cursor, Claude Code, and any other MCP client read and write the same short facts. The data is one SQLite file on your machine. A language model is optional, and search never calls one.

The notebook UI is in German. [Deutsche Anleitung](README.de.md).

## What it stores

Short facts that should still be true next week: a preference, a decision, a convention, a lesson from a bug. Not chat logs, not the current task, not secrets.

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

Dreaming only merges or retires facts that are already stored. It does not invent new ones. With the model switched off, dreaming changes nothing.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- Git, if you want project scopes detected for you
- optional: an API key for DeepSeek or another OpenAI-compatible API

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

`--service` installs a user service: systemd on Linux, launchd on macOS. On Windows, run `memoryforge serve` in the foreground.

| | |
|---|---|
| Config | `~/.config/memoryforge/config.toml` (mode `0600`) |
| Database | `~/.local/share/memoryforge/memory.db` |
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

The sidebar is the scope list. **Alle** shows everything. **Global** shows only global facts. A repository shows that repository, and underneath the global facts an agent would also see there. Search in a repository searches both.

**Merken** stores one fact in the scope selected above the button. **Anderer Scope** is for a scope that does not exist yet. A git URL in that field is normalized. `/` focuses search. Ctrl+Enter or Cmd+Enter submits the note you are typing.

**Anheften** keeps a fact on the session card (`memory_brief`). **Vergessen** hides a fact from search, the list, and MCP. The row stays in the file. **Bearbeiten** replaces the text and refreshes the embedding. The form does not set a kind. With the model off, UI notes are stored as `fact`. With the model on, a longer note may be split or classified.

`autostart` in the config only records the wish. Login startup comes from `memoryforge install-service` or `./install.sh --service`.

## Model

Off is the default. `add` then stores the text as written, unless that exact text already exists in the scope.

On: one short sentence with no close neighbor is still stored as written. Longer notes, and notes that sit next to a similar fact, go to the model. If the API fails, the original text is stored anyway.

Search does not call the API.

| Label in the UI | Model id | Provider |
|---|---|---|
| DeepSeek V4.1 Flash | `deepseek-flash` | `https://api.deepseek.com` |
| DeepSeek V4 Pro | `deepseek-v4-pro` | same |
| GPT-4.1 nano | `gpt-4.1-nano` | `https://api.openai.com/v1` |
| GPT-4.1 mini | `gpt-4.1-mini` | same |
| GPT-4o mini | `gpt-4o-mini` | same |

The label is just a label. The provider has to accept the id. Another id, or a local OpenAI-compatible server, goes in **Eigene Modell-ID**. A filled custom id wins over the list. Choosing a listed model clears the custom field.

```bash
memoryforge config models
memoryforge config set llm.enabled true
memoryforge config set llm.provider deepseek
memoryforge config set llm.base_url https://api.deepseek.com
memoryforge config set llm.model deepseek-flash
memoryforge config set llm.api_key sk-...
memoryforge config set llm.thinking false
memoryforge config show
```

`config show` masks the key. Leave thinking off for extraction.

The embedding model is not this menu. It stays `BAAI/bge-small-en-v1.5` on disk. Changing the chat model does not touch old vectors. Changing the embedding model does: run `memoryforge reembed` afterwards.

```bash
memoryforge dream
memoryforge dream --scope global
```

## CLI

```bash
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
At session start call memory_brief. Pass scope project:<host/owner/repo> when you know the git remote, otherwise omit it.
When you learn a durable preference, decision, convention, or debug lesson, call memory_add with one or a few sentences.
Do not store secrets, tokens, or ephemeral task state.
```

| Tool | Use |
|---|---|
| `memory_brief` | session start: pinned facts, then recent ones |
| `memory_search` | meaning plus full text |
| `memory_add` | store a fact or a raw note |
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
```

`memoryforge config set section.field value`. Booleans: `true`, `false`, `ja`, `nein`, `an`, `aus`.

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

The notebook can download the same zip: **Backup** in the sidebar includes the key. Settings has a second button without it.

## Uninstall

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
