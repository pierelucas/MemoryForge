# MemoryForge

Lokales Gedächtnis für Coding-Agenten. OpenCode, Cursor, Claude Code und jeder andere MCP-Client lesen und schreiben dieselben kurzen Fakten. Die Daten sind eine SQLite-Datei auf deinem Rechner. Ein Sprachmodell ist optional. Die Suche ruft keines.

Die Oberfläche ist standardmäßig englisch, Deutsch lässt sich in den **Einstellungen** wählen. [English](README.md).

## Was gespeichert wird

Kurze Fakten, die nächste Woche noch stimmen sollen: eine Vorliebe, eine Entscheidung, eine Konvention, eine Lehre aus einem Bug. Keine Chatverläufe, keine laufende Aufgabe, keine Secrets.

Jeder Fakt hat einen Scope.

| Scope | Bedeutung |
|---|---|
| `global` | gilt für dich, in jedem Repo |
| `project:host/owner/repo` | gilt für dieses Repository |

Eine Projektsuche liefert auch `global`. Eine globale Suche liefert keine Projektfakten. Schreiben, Ersetzen und Träumen bleiben in einem Scope. Ein Repo-Fakt kann eine Vorliebe nicht überschreiben.

Ohne Scope führen CLI und eine stdio-MCP-Sitzung `git remote get-url origin` im Arbeitsverzeichnis aus.

| Remote | Scope |
|---|---|
| `git@github.com:owner/repo.git` | `project:github.com/owner/repo` |
| `https://github.com/owner/repo.git` | derselbe |
| kein Git oder kein `origin` | `global` |

Der HTTP-Dienst sieht dein Repo nicht. Den Scope musst du mitschicken. Er bindet an `127.0.0.1`, solange du das nicht änderst.

## Was es nicht tut

Kein Konto, keine gehostete Vektordatenbank. Suche und Embeddings bleiben lokal. Zeichenketten, die wie Secrets aussehen (`api_key=…`, `sk-…`, `ghp_…`, private Keys), werden vor dem Speichern geschwärzt. Trotzdem keine Secrets hineingeben.

Träumen fasst nur zusammen oder legt still, was schon gespeichert ist. Es erfindet nichts. Ist das Modell aus, ändert Träumen nichts.

## Voraussetzungen

- Python 3.10 oder neuer
- [uv](https://docs.astral.sh/uv/)
- Git, wenn Projekt-Scopes erkannt werden sollen
- optional ein API-Key für DeepSeek oder eine andere OpenAI-kompatible API

Beim ersten echten Embedding lädt `fastembed` das Modell `BAAI/bge-small-en-v1.5` in den lokalen Cache. Ohne das Paket sucht MemoryForge weiter, mit einem Hash-Embedder plus Volltext. Gedacht für Tests und für Rechner, auf denen der Download nicht hin soll. Die Treffer sind schwächer.

## Installation

```bash
git clone https://github.com/pierelucas/MemoryForge.git
cd MemoryForge
./install.sh
```

Das Skript installiert `uv`, falls es fehlt, und danach das Kommando `memoryforge`. Im Terminal fragt es, ob du sofort ein Modell eintragen willst. `--yes` überspringt die Fragen.

```bash
./install.sh --yes --service
```

`--service` richtet einen Benutzerdienst ein: systemd unter Linux, launchd unter macOS. Unter Windows läuft der Dienst im Vordergrund mit `memoryforge serve`. Der Dienst startet beim Login. Soll er auch ohne Anmeldung laufen, einmalig `loginctl enable-linger "$USER"` ausführen.

| | |
|---|---|
| Konfiguration | `~/.config/memoryforge/config.toml` (Rechte `0600`) |
| Datenbank | `~/.local/share/memoryforge/memory.db` |
| Dienst-Log | `~/.local/share/memoryforge/serve.log` |

`XDG_CONFIG_HOME` und `XDG_DATA_HOME` ersetzen diese Wurzeln.

## Oberfläche

```bash
memoryforge            # Dienst starten, falls er nicht läuft, und die Adresse zeigen
memoryforge ui         # Oberfläche im Browser öffnen
memoryforge serve      # im Vordergrund
memoryforge serve --detach
memoryforge stop
memoryforge doctor
```

Standardadresse: <http://127.0.0.1:4737/>

In der Leiste stehen die Scopes. **Alle** zeigt alles. **Global** nur globale Fakten. Ein Repository zeigt dieses Repository und darunter die globalen Fakten, die ein Agent dort mitliest. Die Suche in einem Repository durchsucht beide. **Scope löschen** auf einer Scope-Seite blendet nach einer Bestätigungsseite alle aktiven Fakten darin aus. Die Zeilen bleiben in der Datei. **Alle** ist eine Ansicht, kein Scope, und hat deshalb keinen Lösch-Link.

**Merken** speichert einen Fakt im Scope über dem Knopf. **Anderer Scope** ist für einen Namen, den es noch nicht gibt. Eine Git-URL in dem Feld wird umgeschrieben. `/` setzt den Fokus in die Suche. Strg+Enter oder Cmd+Enter speichert die Notiz, in der du gerade tippst.

**Anheften** hält einen Fakt in der Session-Karte (`memory_brief`). **Vergessen** blendet ihn aus Suche, Liste und MCP aus. Die Zeile bleibt in der Datei. **Bearbeiten** ersetzt den Text und erneuert das Embedding. Die Scope-Auswahl im Formular verschiebt den Fakt in einen anderen Scope oder unter einen neuen Namen. Ein Umzug in einen Scope, in dem derselbe Text schon steht, wird abgelehnt. Das Formular setzt keine Art. Ohne Modell werden Notizen aus der Oberfläche als `fact` gespeichert. Mit Modell kann eine längere Notiz zerlegt oder eingeordnet werden.

In den **Einstellungen** stehen die KI-Optionen, die Sprache (Englisch oder Deutsch), Prüfen und Träumen sowie der Backup-Download mit und ohne Key.

`autostart` in der Konfiguration merkt sich nur den Wunsch. Der Start beim Login kommt von `memoryforge install-service` oder `./install.sh --service`.

## Modell

Aus ist der Standard. `add` speichert den Text dann wörtlich, sofern er in dem Scope nicht schon exakt existiert.

An: ein kurzer Satz ohne nahen Nachbarn bleibt ebenfalls wörtlich. Längere Notizen und Notizen neben einem ähnlichen Fakt gehen an das Modell. Schlägt die API fehl, bleibt der Originaltext trotzdem erhalten.

Die Suche ruft die API nie.

| Anzeige | Modell-ID | Anbieter |
|---|---|---|
| DeepSeek V4.1 Flash | `deepseek-flash` | `https://api.deepseek.com` |
| DeepSeek V4 Pro | `deepseek-v4-pro` | dieselbe URL |
| GPT-4.1 nano | `gpt-4.1-nano` | `https://api.openai.com/v1` |
| GPT-4.1 mini | `gpt-4.1-mini` | dieselbe URL |
| GPT-4o mini | `gpt-4o-mini` | dieselbe URL |

Die Anzeige ist nur eine Beschriftung. Der Anbieter muss die ID kennen. Eine andere ID oder ein lokaler OpenAI-kompatibler Server kommt in **Eigene Modell-ID**. Ist das Feld gefüllt, gewinnt es gegen die Liste. Die Wahl eines Listeneintrags leert das Feld.

```bash
memoryforge config models
memoryforge config set llm.enabled true
memoryforge config set llm.provider deepseek
memoryforge config set llm.base_url https://api.deepseek.com
memoryforge config set llm.model deepseek-flash
memoryforge config set llm.api_key sk-...
memoryforge config set llm.thinking false
memoryforge config set ui.lang de
memoryforge config show
```

`config show` maskiert den Key. Thinking für die Extraktion aus lassen.

Das Embedding-Modell ist nicht dieses Menü. Es bleibt lokal `BAAI/bge-small-en-v1.5`. Ein Wechsel des Chat-Modells ändert alte Vektoren nicht. Ein Wechsel des Embedding-Modells schon: danach `memoryforge reembed`.

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

stdio ist der richtige Weg. OpenCode startet den Prozess im Projektordner, MemoryForge liest `origin`, und beide benutzen dieselbe Datenbank wie die Oberfläche.

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

Die Werkzeuge tun nichts, wenn der Agent sie nicht aufruft. In die Projektanweisung:

```text
At session start call memory_brief. Pass scope project:<host/owner/repo> when you know the git remote, otherwise omit it.
When you learn a durable preference, decision, convention, or debug lesson, call memory_add with one or a few sentences.
Do not store secrets, tokens, or ephemeral task state.
```

| Werkzeug | Zweck |
|---|---|
| `memory_brief` | Session-Start: Angeheftetes, dann die letzten Fakten |
| `memory_search` | Bedeutung plus Volltext |
| `memory_add` | Fakt oder Rohtext speichern |
| `memory_list` | aktive Zeilen |
| `memory_pin` | anheften oder lösen |
| `memory_forget` | ausblenden |

Cursor, Claude Code und andere Clients auf diesem Rechner nehmen dasselbe stdio-Kommando. Ein Client, der keinen Prozess starten kann, nimmt HTTP, nachdem `memoryforge` läuft:

```text
http://127.0.0.1:4737/mcp
```

Auf dem Port gibt es keine Anmeldung. Nicht ins gemeinsame Netz binden. Auf der Standardbindung weist das Notizbuch Anfragen mit fremdem `Host` ab und blockt Formular-Posts von anderen Origins. `curl` und MCP-Clients ohne Origin bleiben erlaubt.

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

[ui]
lang = "en"
```

`memoryforge config set section.feld wert`. Boolesche Werte: `true`, `false`, `ja`, `nein`, `an`, `aus`. `ui.lang` nimmt `en` oder `de`; fehlt der Wert oder ist er unbekannt, gilt Englisch.

## Umzug

```bash
memoryforge backup
memoryforge backup --without-secrets -o ~/merk.zip
```

Das ZIP enthält drei Dateien, sonst nichts:

```text
manifest.json    Formatversion, Zeitpunkt, Embedding-Modell
config.toml      inklusive API-Key, außer mit --without-secrets
memory.db        SQLite-Backup, keine offene WAL-Datei
```

Programm, Modell-Cache und Logs sind nicht dabei. Der Key steht im Klartext im ZIP, sonst müsstest du ihn auf dem neuen Rechner wieder eintippen. So ein Archiv nicht weitergeben. `--without-secrets` leert den Key.

Auf dem neuen Rechner, im frischen Klon:

```bash
./install.sh --restore memoryforge-backup-20261019-1504.zip
```

Ist das Kommando schon installiert:

```bash
memoryforge restore memoryforge-backup-20261019-1504.zip
memoryforge
```

Der laufende Dienst wird vorher gestoppt. Die Dateien landen in den üblichen Ordnern **dieses** Rechners. Alte Home-Pfade werden nicht mitkopiert. Stimmt das Embedding-Modell im Manifest nicht mit der lokalen Config überein, sagt das Restore das. Danach `memoryforge reembed`.

Ein ZIP mit zusätzlichen Pfaden oder `..` wird abgelehnt. Eine Formatversion, die dieses Programm nicht kennt, ebenfalls. Beides, bevor etwas überschrieben wird.

Dieselbe Datei gibt es in der Oberfläche unter **Einstellungen** → **Umzug**: ein Knopf mit Key, einer ohne Key.

## Deinstallation

```bash
./uninstall.sh            # Dienst und Kommando entfernen, Daten bleiben
./uninstall.sh --purge    # zusätzlich Konfiguration und Datenbank löschen
```

Das Skript stoppt den Dienst, meldet die systemd-Unit ab, entfernt den LaunchAgent auf macOS und deinstalliert das Kommando. `uv` bleibt installiert. Die OpenCode-Konfiguration wird nicht verändert; den `memoryforge`-Eintrag dort von Hand oder unter `/mcps` entfernen.

Von Hand:

```bash
memoryforge stop
uv tool uninstall memoryforge
rm -rf ~/.config/memoryforge ~/.local/share/memoryforge
```

Unter Linux zusätzlich `systemctl --user disable --now memoryforge` und die Unit `~/.config/systemd/user/memoryforge.service` löschen. Unter macOS den LaunchAgent `~/Library/LaunchAgents/com.memoryforge.plist` mit `launchctl unload` entfernen.

## Entwicklung

```bash
uv venv
uv pip install -e ".[dev]"
pytest
memoryforge serve
```

Tests zwingen das Embedding auf den Hash-Fallback (`MEMORYFORGE_EMBED=hash`) und schreiben nicht in deine echte Datenbank.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
