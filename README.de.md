# MemoryForge

Lokales Gedächtnis für Coding-Agenten. OpenCode, Cursor, Claude Code und jeder andere MCP-Client lesen und schreiben dieselben kurzen Fakten. Die Daten sind eine SQLite-Datei auf deinem Rechner. Ein Sprachmodell ist optional. Die Suche ruft keines.

Die Oberfläche ist standardmäßig englisch, Deutsch lässt sich in den **Einstellungen** wählen. [English](README.md).

## Was gespeichert wird

Kurze Fakten, die nächste Woche noch stimmen sollen: eine Vorliebe, eine Entscheidung, eine Konvention, eine Lehre aus einem Bug. Keine Chatverläufe, keine laufende Aufgabe, keine Secrets.

Die Dateien folgen OpenClaw und Claude Code:

| Schicht | Datei | Suche |
|---|---|---|
| Identität | `IDENTITY.md` | Name, Ton, Zeichen. Immergrün. Kein Fakt. |
| Stimme | `SOUL.md` | Haltung und Grenzen. Projekt gewinnt über global. |
| Profil | `USER.md` | immergrüne Vorlieben, als Anweisung geschrieben |
| Dauerhaft | `MEMORY.md` | immergrüne Fakten, Entscheidungen, Konventionen, Lehren |
| Tag | `memory/YYYY-MM-DD.md` | Arbeitsnotizen, Halbwertszeit 30 Tage |
| Prüfung | `DREAMS.md` | Traumtagebuch, wird nicht gesucht und nicht injiziert |

SQLite bleibt die Quelle. Der Markdown-Ordner ist eine Projektion im Datenverzeichnis und wird bei jeder Änderung neu geschrieben. Eine Datei zu bearbeiten ändert die Erinnerung nicht.

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

Träumen erfindet keine Fakten. Ist das Modell aus, ändert es nichts. Ist es an, läuft ein Durchgang in drei Phasen: Light (nahe Dubletten vormerken), REM (ein Prüfungssatz, als Reflexion markiert) und Deep (Dubletten zusammenfassen, eine geeignete Tagesnotiz wörtlich nach `MEMORY.md` oder `USER.md` befördern). Das Tagebuch landet in `DREAMS.md`.

## Voraussetzungen

- Python 3.10 oder neuer
- [uv](https://docs.astral.sh/uv/)
- Git, wenn Projekt-Scopes erkannt werden sollen
- optional ein API-Key für DeepSeek, OpenCode Go oder eine andere OpenAI-kompatible API

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
| Vault | `~/.local/share/memoryforge/vault/` |
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

In der Leiste stehen die Scopes. **Alle** zeigt alles. **Global** nur globale Fakten. **Persona** ist die Stimme für diesen Scope. Die Schicht-Tabs trennen dauerhafte Fakten, Tagesnotizen und das Traumtagebuch. **Dateien** zeigt die Markdown-Projektion; sie zu bearbeiten schreibt nicht zurück. Ein Repository zeigt dieses Repository und darunter die globalen Fakten, die ein Agent dort mitliest. Die Suche in einem Repository durchsucht beide. **Scope löschen** auf einer Projektseite entfernt den Scope nach einer Bestätigung: Erinnerungen, Träume, Persona und die Vault-Dateien werden aus der Datenbank und vom Datenträger gelöscht. **Global** kann nicht gelöscht werden. **Zurücksetzen** leert den Inhalt und lässt den Scope stehen. **Alle** ist eine Ansicht, kein Scope, und hat deshalb keinen Lösch-Link. Ein vorhandenes Backup wird nicht umgeschrieben.

**Merken** speichert einen Fakt im Scope über dem Knopf. **Anderer Scope** ist für einen Namen, den es noch nicht gibt. Eine Git-URL in dem Feld wird umgeschrieben. `/` setzt den Fokus in die Suche. Strg+Enter oder Cmd+Enter speichert die Notiz, in der du gerade tippst.

**Anheften** hält einen Fakt in der Session-Karte (`memory_brief`). **Vergessen** blendet ihn aus Suche, Liste und MCP aus. Die Zeile bleibt in der Datei. **Bearbeiten** ersetzt den Text und erneuert das Embedding. Die Scope-Auswahl im Formular verschiebt den Fakt in einen anderen Scope oder unter einen neuen Namen. Ein Umzug in einen Scope, in dem derselbe Text schon steht, wird abgelehnt. Das Formular setzt keine Art. Ohne Modell werden Notizen aus der Oberfläche als `fact` gespeichert. Mit Modell kann eine längere Notiz zerlegt oder eingeordnet werden.

In den **Einstellungen** stehen die KI-Optionen, die Sprache (Englisch oder Deutsch), Prüfen und Träumen sowie der Backup-Download mit und ohne Key.

`autostart` in der Konfiguration merkt sich nur den Wunsch. Der Start beim Login kommt von `memoryforge install-service` oder `./install.sh --service`.

## Modell

Aus ist der Standard. `add` speichert den Text dann wörtlich, sofern er in dem Scope nicht schon exakt existiert.

An: ein kurzer Satz ohne nahen Nachbarn bleibt ebenfalls wörtlich. Längere Notizen und Notizen neben einem ähnlichen Fakt gehen an das Modell. Schlägt die API fehl, bleibt der Originaltext trotzdem erhalten.

Die Suche ruft die API nie.

Die Anbieterliste umfasst DeepSeek, OpenCode Go, OpenAI, OpenRouter, xAI, Groq, Mistral, Gemini, Cerebras, Together, Fireworks, Moonshot, DashScope, GitHub Models, Hugging Face, NVIDIA, Ollama, LM Studio und jede andere OpenAI-kompatible API.

Die Wahl eines Anbieters setzt die API-Basis. Liegt schon ein Key, oder fügst du einen ein, lädt das Modellmenü die IDs dieses Anbieters. OpenCode Go und OpenRouter veröffentlichen ihre Kataloge, die laden auch ohne Key. Ollama und LM Studio brauchen keinen. Eine gefüllte eigene ID gewinnt. `memoryforge config set llm.provider openai` ersetzt eine Standard-Basis; eine selbst eingetragene URL bleibt.

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

`config show` maskiert den Key. Thinking für die Extraktion aus lassen.

Das Embedding-Modell ist nicht dieses Menü. Es bleibt lokal `BAAI/bge-small-en-v1.5`. Ein Wechsel des Chat-Modells ändert alte Vektoren nicht. Ein Wechsel des Embedding-Modells schon: danach `memoryforge reembed`.

```bash
memoryforge dream
memoryforge dream --scope global
memoryforge note "Heute den Port geprüft."
memoryforge vault
```

`note` schreibt eine Tagesnotiz und ruft das Modell nicht. `vault` schreibt die Markdown-Projektion neu. `memoryforge restore` schreibt sie ebenfalls neu, damit ein altes Vault die wiederhergestellte Datenbank nicht überlebt.

## CLI

```bash
memoryforge persona set soul "Präzise. Kein Fülltext." --scope global
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
memoryforge export -o erinnerungen.json
memoryforge import erinnerungen.json
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
At session start call memory_brief. Read card first. Pass scope project:<host/owner/repo> when you know the git remote, otherwise omit it.
Global persona applies in every repo. Project persona wins if they conflict.
Call memory_persona_set when the user states a name, vibe, or voice. slot is identity or soul.
Call memory_add for a durable preference, decision, convention, or debug lesson, one or a few sentences. Preferences land in USER.md. Other durable facts land in MEMORY.md.
Call memory_note for a working note that should stay in memory/YYYY-MM-DD.md until dreaming promotes it.
When a stored fact changed and you know its id, call memory_update instead of adding a second copy.
Do not store secrets, tokens, or ephemeral task state.
Do not edit the vault files. They are a projection. SQLite is the source of truth. DREAMS.md is review only.
Deleting a project scope in the notebook removes that scope from the database and from disk, including forgotten rows, dreams, persona, and vault files. Global cannot be deleted. Reset clears its contents and leaves the scope in place. Forgetting one memory still only hides that row. An existing backup is not rewritten.
```

| Werkzeug | Zweck |
|---|---|
| `memory_brief` | Session-Start: zuerst `card` lesen. Persona, Anweisungen, angeheftete Fakten, letzte Notizen |
| `memory_persona_set` | `identity` oder `soul` setzen. Leerer Text löscht den Slot |
| `memory_search` | Bedeutung plus Volltext |
| `memory_add` | dauerhaften Fakt speichern |
| `memory_note` | Tagesnotiz speichern; Träumen kann sie später befördern |
| `memory_update` | Text einer Zeile ersetzen oder sie verschieben |
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
