# MemoryForge

Lokales Gedächtnis für Coding-Agenten. OpenCode, Cursor, Claude Code und jeder andere MCP-Client lesen und schreiben dieselben Fakten. Die Daten liegen in einer SQLite-Datei auf deinem Rechner. Ein Sprachmodell ist optional und wird nur beim Verdichten und beim Dreaming gerufen, nie bei der Suche.

## Was es tut

- speichert kurze, dauerhafte Fakten, keine ganzen Chatverläufe
- sucht per lokalem Embedding und Volltext
- trennt `global` (du) von `project:host/owner/repo` (ein Repository)
- spricht MCP, über stdio und über HTTP
- zeigt die Erinnerungen in einem Notizbuch auf `127.0.0.1`
- packt alles in ein ZIP, damit du auf einen anderen Rechner umziehen kannst

## Was es nicht tut

- kein Cloud-Konto, kein Vektor-Server, kein Neo4j
- die Suche schickt nichts aus dem Haus
- Secrets (`api_key=…`, `sk-…`, `ghp_…`, private Keys) werden vor dem Speichern geschwärzt, aber du solltest sie gar nicht erst hineingeben
- Dreaming erfindet keine Fakten. Es darf nur zusammenfassen, was schon dasteht

## Voraussetzungen

- Python 3.10 oder neuer, installiert über [uv](https://docs.astral.sh/uv/)
- Git, wenn Projekt-Scopes automatisch erkannt werden sollen
- optional ein API-Key für DeepSeek oder eine andere OpenAI-kompatible API

Beim ersten echten Embedding lädt `fastembed` das Modell `BAAI/bge-small-en-v1.5` einmalig in den lokalen Cache. Ohne dieses Paket sucht MemoryForge weiter, dann nur über einen Hash-Fallback plus Volltext.

## Neu installieren

```bash
git clone https://github.com/pierelucas/MemoryForge.git
cd MemoryForge
./install.sh
```

Das Skript installiert `uv`, falls es fehlt, und danach `memoryforge` als Kommando. Mit einem Terminal fragt es, ob du sofort eine KI hinterlegen willst. `--yes` überspringt die Fragen.

```bash
./install.sh --yes --service
```

`--service` richtet einen Benutzerdienst ein: systemd unter Linux, launchd unter macOS. Windows startest du im Vordergrund mit `memoryforge serve`.

Pfade danach:

| | |
|---|---|
| Konfiguration | `~/.config/memoryforge/config.toml` (Rechte `0600`) |
| Datenbank | `~/.local/share/memoryforge/memory.db` |
| Dienst-Log | `~/.local/share/memoryforge/serve.log` |

Unter `XDG_CONFIG_HOME` und `XDG_DATA_HOME` gelten diese stattdessen.

## Oberfläche und Dienst

```bash
memoryforge            # Dienst starten, falls er nicht läuft, und die Adresse zeigen
memoryforge ui         # Notizbuch im Browser öffnen
memoryforge serve      # im Vordergrund
memoryforge serve --detach
memoryforge stop
memoryforge doctor
```

Standardadresse: <http://127.0.0.1:4737/>

Die Oberfläche ist ein Notizbuch: links die Scopes, oben die Suche, darunter neue Erinnerungen. Anheften hält einen Fakt in der Session-Karte. Vergessen blendet ihn aus, löscht die Zeile aber nicht hart aus der Datei. Unter Einstellungen schaltest du die KI an, wählst Anbieter und Modell und prüfst die Verbindung.

`autostart` in der Konfiguration merkt sich nur deinen Wunsch. Der tatsächliche Login-Start kommt von `memoryforge install-service` bzw. `./install.sh --service`.

## KI an, aus, Modellwahl

Aus ist der Standard. Dann speichert `add` den Text wörtlich, sofern er nicht schon exakt existiert.

An heißt: ein einzelner kurzer Satz ohne starken Nachbarn wird ebenfalls wörtlich gespeichert. Längere Notizen und Widersprüche gehen an das Modell. Schlägt die API fehl, bleibt der Text trotzdem erhalten.

Die Suche ruft die API nie.

Mitgelieferte Modelle:

| Anzeige | Modell-ID | Anbieter |
|---|---|---|
| DeepSeek V4.1 Flash | `deepseek-flash` | `https://api.deepseek.com` |
| DeepSeek V4 Pro | `deepseek-v4-pro` | dieselbe URL |
| GPT-4.1 nano | `gpt-4.1-nano` | `https://api.openai.com/v1` |
| GPT-4.1 mini | `gpt-4.1-mini` | dieselbe URL |
| GPT-4o mini | `gpt-4o-mini` | dieselbe URL |

Eine andere ID, zum Beispiel ein kleineres GPT-Modell oder ein lokaler OpenAI-kompatibler Server, trägst du als eigene Modell-ID ein. Ist das Feld gefüllt, gewinnt es gegenüber der Liste.

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

`config show` maskiert den Key. Thinking lass für Extraktion aus. Der Schalter ist nur da, weil manche Modelle ihn sonst selbst einschalten.

Das Embedding-Modell ist nicht dieses Menü. Es bleibt lokal (`BAAI/bge-small-en-v1.5`). Ein Wechsel der Chat-Modelle ändert alte Vektoren nicht. Ein Wechsel des Embedding-Modells schon: danach `memoryforge reembed`.

Dreaming fasst Dubletten innerhalb eines Scopes zusammen und markiert die alten Zeilen als überholt.

```bash
memoryforge dream
memoryforge dream --scope global
```

Ist die KI aus, ändert Dreaming nichts.

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

Ohne `--scope` nimmt die CLI den `origin` des aktuellen Git-Repos, sonst `global`. Ein Remote `git@github.com:owner/repo.git` wird zu `project:github.com/owner/repo`.

## OpenCode

Empfohlen ist stdio. OpenCode startet den Prozess im Projektordner, MemoryForge liest den Git-Remote und legt den Scope selbst fest. Die Datei ist dieselbe, die die Oberfläche benutzt.

In `~/.config/opencode/opencode.json` (OpenCode 2) oder in der Projekt-Config:

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

Ältere Configs ohne `servers`:

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

Damit der Agent die Werkzeuge auch benutzt, ein kurzer Abschnitt in der Projektanweisung:

```text
At session start call memory_brief. Pass scope project:<host/owner/repo> when you know the git remote, otherwise omit it.
When you learn a durable preference, decision, convention, or debug lesson, call memory_add with one or a few sentences.
Do not store secrets, tokens, or ephemeral task state.
```

Werkzeuge:

| Werkzeug | Zweck |
|---|---|
| `memory_brief` | Session-Start: Angeheftetes und die letzten Fakten |
| `memory_search` | Bedeutung plus Volltext |
| `memory_add` | Fakt oder Rohtext speichern |
| `memory_list` | Aktive Einträge |
| `memory_pin` | An die Karte heften oder lösen |
| `memory_forget` | Ausblenden |

Für Cursor, Claude Code und andere Clients auf **diesem** Rechner geht dasselbe stdio-Kommando. Für einen Client, der keinen Prozess starten kann, zuerst `memoryforge` und dann die HTTP-Adresse:

```text
http://127.0.0.1:4737/mcp
```

Der HTTP-Dienst errät den Projektordner nicht, weil er nicht in deinem Repo steht. Dann musst du `scope` mitschicken. Der Dienst bindet standardmäßig nur an `127.0.0.1`.

## Konfiguration

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

Felder setzt du mit `memoryforge config set section.feld wert`. Boolesche Werte: `true`, `false`, `ja`, `nein`, `an`, `aus`.

## Backup und Umzug

```bash
memoryforge backup
memoryforge backup --without-secrets -o ~/merk.zip
```

Das ZIP enthält genau drei Dateien:

```text
manifest.json    Formatversion, Zeitpunkt, Embedding-Modell
config.toml      inklusive API-Key, außer mit --without-secrets
memory.db        SQLite-Backup, keine offene WAL-Datei
```

Nicht enthalten: das Programm, der Modell-Cache, Logs. Der Key steht im Klartext im ZIP, sonst müsstest du ihn auf dem neuen Rechner wieder eintippen. Gib so ein Archiv nicht weiter. `--without-secrets` leert den Key.

Auf dem neuen Rechner, im geklonten Repo:

```bash
./install.sh --restore memoryforge-backup-20261019-1504.zip
```

Ist das Kommando schon installiert, reicht:

```bash
memoryforge restore memoryforge-backup-20261019-1504.zip
memoryforge
```

Der laufende Dienst wird vorher gestoppt. Die Dateien landen in den üblichen Ordnern **dieses** Rechners, alte Home-Pfade werden nicht mitkopiert. Stimmt das Embedding-Modell im Manifest nicht mit der lokalen Config überein, sagt das Restore das, und du führst `memoryforge reembed` aus.

Ein fremdes ZIP mit zusätzlichen Pfaden oder `..` wird abgelehnt. Formatversionen, die dieses Programm nicht kennt, ebenfalls, und zwar bevor etwas überschrieben wird.

## Deinstallation

```bash
memoryforge stop
uv tool uninstall memoryforge
rm -rf ~/.config/memoryforge ~/.local/share/memoryforge
```

Unter Linux zusätzlich `systemctl --user disable --now memoryforge` und die Unit unter `~/.config/systemd/user/memoryforge.service` löschen. Unter macOS den LaunchAgent `~/Library/LaunchAgents/com.memoryforge.plist` mit `launchctl unload` entfernen.

## Entwicklung

```bash
uv venv
uv pip install -e ".[dev]"
pytest
memoryforge serve
```

Tests zwingen das Embedding auf den Hash-Fallback (`MEMORYFORGE_EMBED=hash`) und schreiben nicht in dein echtes Notizbuch.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
