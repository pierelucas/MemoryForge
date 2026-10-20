"""UI strings. English is the base, German is an overlay.

Only the notebook is translated. CLI output and service errors stay German.
"""

from __future__ import annotations

LANGS = ("en", "de")
DEFAULT_LANG = "en"

EN: dict[str, str] = {
    # Navigation
    "nav.scopes": "Scopes",
    "nav.all": "All",
    "nav.global": "Global",
    "nav.settings": "Settings",
    # Index
    "index.title": "Memories · MemoryForge",
    "index.pinned": "Pinned",
    "index.pin": "Pin",
    "index.unpin": "Unpin",
    "index.forget": "Forget",
    "index.edit": "Edit",
    "index.save": "Save",
    "index.search": "Search",
    "index.clear": "Clear",
    "index.new": "New memory",
    "index.composer_placeholder": "One sentence that will still be true next week. No keys.",
    "index.remember": "Remember",
    "index.scope": "Scope",
    "index.other_scope": "Other scope",
    "index.scope_name": "New or full name",
    "index.scope_custom_hint": "If this field is filled, it wins over the select above. A git URL is normalized.",
    "index.matches": "{count} matches for “{query}”.",
    "index.lede_global": "Applies in every project. Agents read this too, whichever repo they are in.",
    "index.lede_project": "This repository. Below it are the global facts that are also read here.",
    "index.lede_all": "Everything that is stored. A project search only sees that project plus Global.",
    "index.empty_search": "Nothing found.",
    "index.empty_view": "Nothing in this view yet.",
    "index.empty_project": "Nothing in this project yet.",
    "index.global_section": "Global",
    "index.global_section_hint": "read here too",
    "index.delete_scope": "Delete scope",
    # Forget
    "forget.title": "Forget · MemoryForge",
    "forget.heading": "Forget?",
    "forget.lede": "The row disappears from search, list, and MCP. It stays in the database; it is not hard deleted.",
    "forget.action": "Forget",
    "forget.cancel": "Cancel",
    # Delete scope
    "scope_forget.title": "Delete scope · MemoryForge",
    "scope_forget.heading": "Delete scope?",
    "scope_forget.lede": "All {count} active memories in this scope disappear from search, list, and MCP. The rows stay in the database.",
    "scope_forget.action": "Delete scope",
    "scope_forget.cancel": "Cancel",
    # Settings
    "settings.title": "Settings · MemoryForge",
    "settings.heading": "Settings",
    "settings.lede": "Search and embeddings stay on this machine. A model is only called when the AI is on.",
    "settings.language": "Language",
    "settings.lang_en": "English",
    "settings.lang_de": "German",
    "settings.ai_on": "AI on",
    "settings.ai_on_hint": "Long notes are condensed, contradictions replaced. Short new sentences stay verbatim. If the API fails, the text is still stored.",
    "settings.provider": "Provider",
    "settings.base_url": "API base",
    "settings.model": "Model",
    "settings.model_custom": "Custom model ID",
    "settings.model_other": "Other ID",
    "settings.model_custom_placeholder": "only fill in when the list does not fit",
    "settings.model_hint": "A custom ID wins over the list. The provider must know the ID; the display name in the list is only a label.",
    "settings.thinking": "Thinking",
    "settings.thinking_hint": "Off for extraction. Some models turn it on by themselves otherwise.",
    "settings.api_key": "API key",
    "settings.key_set": "set, leave empty to keep",
    "settings.key_unset": "not set",
    "settings.clear_key": "Delete key",
    "settings.clear_key_hint": "Removes the stored key when you save.",
    "settings.save": "Save",
    "settings.check_dream": "Check and dream",
    "settings.check_dream_hint": "The check makes one short call. Dreaming merges duplicates and marks the old rows as superseded. From here it runs over every scope, each one on its own.",
    "settings.test": "Test connection",
    "settings.dream": "Dream",
    "settings.move": "Move",
    "settings.move_hint": "The zip contains database and configuration. With the key you can continue on the new machine right away. Without the key the archive is easier to share, but you have to enter the key there again.",
    "settings.backup_key": "Backup with key",
    "settings.backup_no_key": "Backup without key",
    # Kinds
    "kind.preference": "Preference",
    "kind.decision": "Decision",
    "kind.convention": "Convention",
    "kind.fact": "Fact",
    "kind.debug": "Debug",
    # Providers
    "provider.custom": "OpenAI-compatible",
    # Flash messages
    "flash.saved": "Saved.",
    "flash.already_saved": "Already saved.",
    "flash.nothing_new": "Nothing new saved.",
    "flash.updated": "Updated.",
    "flash.forgotten": "Forgotten.",
    "flash.scope_forgotten": "Scope deleted, {count} memories.",
    "flash.ai_off": "AI is off.",
    "flash.reachable": "Reachable, model {model}.",
    "flash.done": "Done.",
    "error.empty_text": "Empty text.",
    "error.invalid_scope": "Invalid scope.",
    "error.already_in_scope": "This text already exists in {scope}.",
    "error.forgotten_move": "A forgotten memory cannot be moved.",
    # Dream
    "dream.off": "AI is off. Dreaming changed nothing.",
    "dream.too_few": "Too few memories to dream about.",
    "dream.done": "{changed} memories adjusted, {reviewed} reviewed.",
}

DE: dict[str, str] = {
    # Navigation
    "nav.scopes": "Scopes",
    "nav.all": "Alle",
    "nav.global": "Global",
    "nav.settings": "Einstellungen",
    # Index
    "index.title": "Erinnerungen · MemoryForge",
    "index.pinned": "Angeheftet",
    "index.pin": "Anheften",
    "index.unpin": "Lösen",
    "index.forget": "Vergessen",
    "index.edit": "Bearbeiten",
    "index.save": "Speichern",
    "index.search": "Suchen",
    "index.clear": "Leeren",
    "index.new": "Neue Erinnerung",
    "index.composer_placeholder": "Ein Satz, der nächste Woche noch stimmt. Keine Keys.",
    "index.remember": "Merken",
    "index.scope": "Scope",
    "index.other_scope": "Anderer Scope",
    "index.scope_name": "Neuer oder voller Name",
    "index.scope_custom_hint": "Wenn das Feld gefüllt ist, gilt es statt der Auswahl oben. Eine Git-URL wird umgeschrieben.",
    "index.matches": "{count} Treffer für „{query}“.",
    "index.lede_global": "Gilt in jedem Projekt. Agenten lesen das hier mit, egal in welchem Repo sie stehen.",
    "index.lede_project": "Dieses Repository. Darunter die globalen Fakten, die hier mitgelesen werden.",
    "index.lede_all": "Alles, was gespeichert ist. Die Suche eines Projekts sieht nur dieses Projekt plus Global.",
    "index.empty_search": "Nichts gefunden.",
    "index.empty_view": "Noch nichts in dieser Ansicht.",
    "index.empty_project": "In diesem Projekt liegt noch nichts.",
    "index.global_section": "Global",
    "index.global_section_hint": "wird hier mitgelesen",
    "index.delete_scope": "Scope löschen",
    # Forget
    "forget.title": "Vergessen · MemoryForge",
    "forget.heading": "Vergessen?",
    "forget.lede": "Die Zeile verschwindet aus Suche, Liste und MCP. In der Datenbank bleibt sie stehen, sie wird nicht hart gelöscht.",
    "forget.action": "Vergessen",
    "forget.cancel": "Abbrechen",
    # Delete scope
    "scope_forget.title": "Scope löschen · MemoryForge",
    "scope_forget.heading": "Scope löschen?",
    "scope_forget.lede": "Alle {count} aktiven Erinnerungen in diesem Scope verschwinden aus Suche, Liste und MCP. Die Zeilen bleiben in der Datenbank.",
    "scope_forget.action": "Scope löschen",
    "scope_forget.cancel": "Abbrechen",
    # Settings
    "settings.title": "Einstellungen · MemoryForge",
    "settings.heading": "Einstellungen",
    "settings.lede": "Suche und Embeddings bleiben auf diesem Rechner. Ein Modell wird nur gerufen, wenn die KI an ist.",
    "settings.language": "Sprache",
    "settings.lang_en": "Englisch",
    "settings.lang_de": "Deutsch",
    "settings.ai_on": "KI an",
    "settings.ai_on_hint": "Lange Notizen werden dann verdichtet, Widersprüche ersetzt. Kurze neue Sätze bleiben wörtlich. Schlägt die API fehl, wird der Text trotzdem gespeichert.",
    "settings.provider": "Anbieter",
    "settings.base_url": "API-Basis",
    "settings.model": "Modell",
    "settings.model_custom": "Eigene Modell-ID",
    "settings.model_other": "Andere ID",
    "settings.model_custom_placeholder": "nur ausfüllen, wenn die Liste nicht passt",
    "settings.model_hint": "Eine eigene ID gewinnt gegen die Liste. Die ID muss der Anbieter kennen, der Anzeigename in der Liste ist nur eine Beschriftung.",
    "settings.thinking": "Thinking",
    "settings.thinking_hint": "Für Extraktion aus lassen. Manche Modelle schalten es sonst selbst ein.",
    "settings.api_key": "API-Key",
    "settings.key_set": "gesetzt, leer lassen zum Behalten",
    "settings.key_unset": "nicht gesetzt",
    "settings.clear_key": "Key löschen",
    "settings.clear_key_hint": "Entfernt den gespeicherten Schlüssel beim Speichern.",
    "settings.save": "Speichern",
    "settings.check_dream": "Prüfen und träumen",
    "settings.check_dream_hint": "Die Prüfung macht einen kurzen Aufruf. Träumen fasst Dubletten zusammen und markiert die alten Zeilen als überholt. Von hier aus über alle Scopes, jeweils innerhalb eines Scopes.",
    "settings.test": "Verbindung prüfen",
    "settings.dream": "Träumen",
    "settings.move": "Umzug",
    "settings.move_hint": "Das ZIP enthält Datenbank und Konfiguration. Mit Key kannst du auf dem neuen Rechner direkt weiterarbeiten. Ohne Key teilst du das Archiv leichter, musst den Schlüssel dort neu eintragen.",
    "settings.backup_key": "Backup mit Key",
    "settings.backup_no_key": "Backup ohne Key",
    # Kinds
    "kind.preference": "Vorliebe",
    "kind.decision": "Entscheidung",
    "kind.convention": "Konvention",
    "kind.fact": "Fakt",
    "kind.debug": "Debug",
    # Providers
    "provider.custom": "OpenAI-kompatibel",
    # Flash messages
    "flash.saved": "Gespeichert.",
    "flash.already_saved": "War schon gespeichert.",
    "flash.nothing_new": "Nichts Neues gespeichert.",
    "flash.updated": "Aktualisiert.",
    "flash.forgotten": "Vergessen.",
    "flash.scope_forgotten": "Scope gelöscht, {count} Erinnerungen.",
    "flash.ai_off": "KI ist aus.",
    "flash.reachable": "Erreichbar, Modell {model}.",
    "flash.done": "Fertig.",
    "error.empty_text": "Leerer Text.",
    "error.invalid_scope": "Ungültiger Scope.",
    "error.already_in_scope": "Dieser Text steht schon in {scope}.",
    "error.forgotten_move": "Vergessene Erinnerungen lassen sich nicht verschieben.",
    # Dream
    "dream.off": "KI ist aus. Dreaming hat nichts geändert.",
    "dream.too_few": "Zu wenige Erinnerungen zum Träumen.",
    "dream.done": "{changed} Erinnerungen angepasst, {reviewed} geprüft.",
}

CATALOG = {"en": EN, "de": DE}


def normalize_lang(value: str | None) -> str:
    text = (value or "").strip().lower()
    return text if text in LANGS else DEFAULT_LANG


def translate(lang: str | None, key: str, default: str | None = None, **params) -> str:
    chosen = normalize_lang(lang)
    text = CATALOG[chosen].get(key)
    if text is None:
        text = EN.get(key)
    if text is None:
        text = default if default is not None else key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def kind_label(lang: str | None, kind: str) -> str:
    return translate(lang, f"kind.{kind}")
