from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memoryforge.config import KINDS, Config, load_config
from memoryforge.db import Store, clamp_limit, cosine, fts_query
from memoryforge.embed import Embedder, get_embedder
from memoryforge.llm import ChatLLM, LLMError
from memoryforge.paths import db_path
from memoryforge.safety import redact
from memoryforge.scope import detect_scope, normalize_scope

_guard = threading.Lock()
_service: MemoryService | None = None
_service_key: tuple | None = None
DAILY_HALF_LIFE_DAYS = 30


class MemoryError(ValueError):
    """A user-facing error with a key for the translated UI."""

    def __init__(self, key: str, german: str, **params) -> None:
        self.key = key
        self.params = params
        super().__init__(german)


class MemoryService:
    def __init__(self, cfg: Config, store: Store | None = None, embedder: Embedder | None = None, llm=None) -> None:
        self.cfg = cfg
        self.store = store or Store(db_path())
        self.embedder = embedder or get_embedder(cfg.embed.model)
        self.llm = llm if llm is not None else ChatLLM(cfg)

    def close(self) -> None:
        self.store.close()

    def add(
        self,
        text: str,
        *,
        scope: str | None = None,
        source: str = "cli",
        detect: bool = False,
    ) -> dict:
        cleaned = redact(text)
        if not cleaned:
            raise ValueError("Leerer Text.")
        resolved = normalize_scope(scope) if scope else ""
        if not resolved:
            resolved = detect_scope() if detect else "global"
        exact = self.store.find_exact(resolved, cleaned)
        if exact:
            return {"memories": [exact], "noop": True, "llm": False}

        use_llm = bool(self.cfg.llm.enabled)
        neighbors = self.search(cleaned, scope=resolved, limit=5, include_global=False)
        strong = [item for item in neighbors if item.get("score", 0) >= 0.86 and item["text"].strip().lower() != cleaned.lower()]
        if not use_llm or (_atomic(cleaned) and not strong):
            memory = self._insert(cleaned, resolved, "fact", source, confidence=1.0)
            self._sync(resolved)
            return {"memories": [memory], "noop": False, "llm": False}

        try:
            actions = self.llm.extract(cleaned, resolved, neighbors[:5])
        except LLMError:
            memory = self._insert(cleaned, resolved, "fact", source, confidence=0.5)
            self._sync(resolved)
            return {"memories": [memory], "noop": False, "llm": False, "warning": "Extraktion fehlgeschlagen, Text wörtlich gespeichert."}
        if not actions or all(action.get("op") == "noop" for action in actions):
            # The model explicitly said there is nothing new. Do not store a
            # fallback copy; only report what the note already referred to.
            references: list[str] = []
            for action in actions:
                values = action.get("replaces") or []
                if isinstance(values, str):
                    values = [values]
                references.extend(value for value in values if isinstance(value, str))
            existing = [
                row
                for row in self.store.get_many(references)
                if row["scope"] == resolved and not row["forgotten"] and not row["superseded_by"]
            ]
            return {"memories": existing, "noop": True, "llm": True}
        memories = self.apply_actions(actions, scope=resolved, source=source, fallback=cleaned)
        self._sync(resolved)
        return {"memories": memories, "noop": not memories, "llm": True}

    def apply_actions(self, actions: list[dict], *, scope: str, source: str, fallback: str | None = None) -> list[dict]:
        stored: list[dict] = []
        changed = False
        for action in actions:
            op = action.get("op")
            if op == "noop":
                continue
            text = redact(action.get("text") or "")
            if not text:
                continue
            kind = action.get("kind") if action.get("kind") in KINDS else "fact"
            if op == "supersede":
                replaces = action.get("replaces") or []
                if isinstance(replaces, str):
                    replaces = [replaces]
                existing = self.store.find_exact(scope, text)
                if existing:
                    # The merged text already exists; retire the old rows and
                    # reuse that row instead of adding a duplicate.
                    self.store.supersede(replaces, existing["id"], scope=scope)
                    stored.append(existing)
                    changed = True
                    continue
                memory = self._insert(text, scope, kind, source, confidence=0.8)
                self.store.supersede(replaces, memory["id"], scope=scope)
                stored.append(memory)
                changed = True
            elif op == "add":
                if self.store.find_exact(scope, text):
                    continue
                stored.append(self._insert(text, scope, kind, source, confidence=0.8))
                changed = True
        if not changed and fallback:
            if not self.store.find_exact(scope, fallback):
                stored.append(self._insert(fallback, scope, "fact", source, confidence=0.6))
        return stored

    def note(
        self,
        text: str,
        *,
        scope: str | None = None,
        source: str = "cli",
        detect: bool = False,
    ) -> dict:
        """Store a working note. Dreaming may promote it later. The text is not rewritten."""
        cleaned = redact(text)
        if not cleaned:
            raise ValueError("Leerer Text.")
        resolved = normalize_scope(scope) if scope else ""
        if not resolved:
            resolved = detect_scope() if detect else "global"
        exact = self.store.find_exact(resolved, cleaned)
        if exact:
            return {"memories": [exact], "noop": True, "llm": False}
        memory = self._insert(cleaned, resolved, "fact", source, confidence=0.7, tier="daily")
        self._sync(resolved)
        return {"memories": [memory], "noop": False, "llm": False}

    def _insert(
        self,
        text: str,
        scope: str,
        kind: str,
        source: str,
        confidence: float,
        tier: str = "durable",
    ) -> dict:
        embedding = self.embedder.embed_many([text])[0]
        return self.store.insert(
            text=text,
            scope=scope,
            kind=kind,
            source=source,
            embedding=embedding,
            confidence=confidence,
            tier=tier,
        )

    def search(
        self,
        query: str,
        *,
        scope: str | None = None,
        limit: int = 8,
        include_global: bool | None = None,
        record: bool = False,
    ) -> list[dict]:
        limit = clamp_limit(limit, 200)
        resolved = normalize_scope(scope) if scope else ""
        if include_global is None:
            include_global = bool(resolved) and resolved != "global"
        cleaned = query.strip()
        if not cleaned:
            return self.store.list_memories(scope=resolved or None, include_global=include_global, limit=limit)
        vector = self.embedder.embed_many([cleaned])[0]
        vector_scores: dict[str, float] = {}
        for memory_id, embedding in self.store.vectors_for(resolved or None, include_global):
            vector_scores[memory_id] = cosine(vector, embedding)
        fts_scores: dict[str, float] = {}
        match = fts_query(cleaned)
        if match:
            fts_scores = self.store.fts(match, resolved or None, include_global)
        ids = set(vector_scores) | set(fts_scores)
        ranked: list[tuple[float, str]] = []
        for memory_id in ids:
            score = 0.72 * vector_scores.get(memory_id, 0.0) + 0.28 * fts_scores.get(memory_id, 0.0)
            ranked.append((score, memory_id))
        ranked = [(score, memory_id) for score, memory_id in ranked if score > 0]
        by_id = {item["id"]: item for item in self.store.get_many([memory_id for _, memory_id in ranked])}
        results = []
        for score, memory_id in ranked:
            row = by_id.get(memory_id)
            if row is None:
                continue
            # Boost before sorting. Adding it afterwards only changed the
            # displayed number, never the order.
            score *= importance_weight(row.get("importance"))
            score *= recency_weight(
                row.get("tier") or "durable",
                bool(row["pinned"]),
                row.get("updated_at") or row.get("created_at"),
            )
            if row["pinned"]:
                score += 0.04
            shown = dict(row)
            shown["score"] = round(score, 4)
            results.append(shown)
        results.sort(key=lambda item: item["score"], reverse=True)
        found = results[:limit]
        if record and found:
            self.store.note_recalls([row["id"] for row in found])
            for row in found:
                row["recalls"] = int(row.get("recalls") or 0) + 1
        return found

    def brief(self, scope: str | None = None, *, detect: bool = False) -> dict:
        resolved = normalize_scope(scope) if scope else ""
        if not resolved and detect:
            resolved = detect_scope()
        include_global = bool(resolved) and resolved != "global"
        pinned = self.store.list_memories(scope=resolved or None, include_global=include_global, limit=8, pinned_only=True)
        directives = self.store.list_memories(
            scope=resolved or None,
            include_global=include_global,
            limit=6,
            tier="durable",
            kind="preference",
        )
        durable = self.store.list_memories(
            scope=resolved or None,
            include_global=include_global,
            limit=8,
            tier="durable",
        )
        since = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        daily = self.store.list_recent_daily(
            scope=resolved or None,
            include_global=include_global,
            since=since.isoformat(),
            limit=6,
        )
        standing = [item for item in pinned if item["id"] not in {row["id"] for row in directives}]
        other = [item for item in durable if item.get("kind") != "preference" and not item.get("pinned")]
        seen: set[str] = set()
        memories: list[dict] = []
        for bucket in (pinned, directives, durable, daily):
            for item in bucket:
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                memories.append(item)
                if len(memories) >= 12:
                    break
            if len(memories) >= 12:
                break
        persona = self.persona_view(resolved or None)
        if resolved:
            self._sync(resolved)
            if include_global:
                self._sync("global")
        else:
            self._sync()
        from memoryforge.persona import context_card
        from memoryforge.vault import vault_dir, vault_files

        files = vault_files(resolved) if resolved else {"index": str(vault_dir() / "INDEX.md")}
        card = context_card(
            scope=resolved or "all",
            persona=persona,
            directives=directives,
            standing=standing[:4],
            durable=other[:4],
            daily=daily[:4],
        )
        return {
            "scope": resolved or "all",
            "card": card,
            "persona": persona,
            "memories": memories[:12],
            "directives": directives,
            "durable": other[:6],
            "daily": daily,
            "files": files,
        }

    def persona_view(self, scope: str | None) -> dict:
        resolved = scope or ""
        wanted = ["global"]
        if resolved and resolved != "global":
            wanted.append(resolved)
        stored = self.store.personas_in(wanted)
        view = {
            "global": stored.get("global") or {"identity": "", "soul": ""},
            "project": None,
        }
        if resolved and resolved != "global":
            view["project"] = stored.get(resolved) or {"identity": "", "soul": ""}
        return view

    def set_persona(self, scope: str, slot: str, text: str) -> dict | None:
        from memoryforge.persona import PersonaError, clean_persona, normalize_slot

        resolved = normalize_scope(scope) or "global"
        try:
            chosen = normalize_slot(slot)
            cleaned = clean_persona(chosen, text)
        except PersonaError as exc:
            raise MemoryError(exc.key, str(exc)) from exc
        if not cleaned:
            self.store.delete_persona(resolved, chosen)
            self._sync(resolved)
            return None
        row = self.store.set_persona(resolved, chosen, cleaned)
        self._sync(resolved)
        return row

    def list_memories(self, scope: str | None = None, limit: int = 50, *, tier: str | None = None) -> list[dict]:
        resolved = normalize_scope(scope) if scope else ""
        return self.store.list_memories(
            scope=resolved or None,
            include_global=False,
            limit=clamp_limit(limit),
            tier=tier,
        )

    def list_dreams(self, scope: str | None = None, limit: int = 40) -> list[dict]:
        resolved = normalize_scope(scope) if scope else ""
        return self.store.list_dreams(resolved or None, limit=limit)

    def forget(self, memory_id: str) -> None:
        current = self.store.get(memory_id)
        self.store.forget(memory_id)
        if current:
            self._sync(current["scope"])

    def scope_footprint(self, scope: str) -> dict:
        resolved = normalize_scope(scope) if scope else ""
        empty = {"memories": 0, "dreams": 0, "personas": 0, "vault": False}
        if not resolved:
            return empty
        counts = self.store.scope_counts(resolved)
        try:
            from memoryforge.vault import scope_dir

            path = scope_dir(resolved)
            counts["vault"] = path.exists() or path.is_symlink()
        except OSError:
            counts["vault"] = False
        return counts

    def has_scope_data(self, scope: str) -> bool:
        foot = self.scope_footprint(scope)
        return bool(foot["memories"] or foot["dreams"] or foot["personas"] or foot["vault"])

    def residue_scopes(self) -> list[str]:
        return self.store.residue_scopes()

    def forget_scope(self, scope: str) -> int:
        """Remove a scope and everything that belongs to it, on disk as well as in the UI."""
        resolved = normalize_scope(scope)
        if not resolved:
            raise MemoryError("error.invalid_scope", "Ungültiger Scope.")
        if resolved == "global":
            raise MemoryError("error.global_scope", "Global kann nicht gelöscht werden.")
        if not self.has_scope_data(resolved):
            raise KeyError(resolved)
        counts = self.store.purge_scope(resolved)
        self._drop_projection(resolved)
        return counts["memories"]

    def reset_scope(self, scope: str) -> int:
        """Clear Global. The scope stays; its rows and files do not."""
        resolved = normalize_scope(scope) or ""
        if resolved != "global":
            raise MemoryError("error.global_scope", "Nur Global kann zurückgesetzt werden.")
        if not self.has_scope_data("global"):
            raise KeyError("global")
        counts = self.store.purge_scope("global")
        self._drop_projection("global")
        self._sync("global")
        return counts["memories"]

    def pin(self, memory_id: str, pinned: bool = True) -> dict:
        row = self.store.set_pinned(memory_id, pinned)
        self._sync(row["scope"])
        return row

    def update(self, memory_id: str, text: str, scope: str | None = None) -> dict:
        current = self.store.get(memory_id)
        if current is None:
            raise KeyError(memory_id)
        if current["forgotten"] or current["superseded_by"]:
            raise MemoryError("error.inactive", "Diese Erinnerung ist nicht mehr aktiv.")
        cleaned = redact(text)
        if not cleaned:
            raise MemoryError("error.empty_text", "Leerer Text.")
        target = normalize_scope(scope) if scope else current["scope"]
        if not target:
            raise MemoryError("error.invalid_scope", "Ungültiger Scope.")
        # The same text must stay unique within a scope, whether the row is
        # moved or only edited.
        exact = self.store.find_exact(target, cleaned)
        if exact and exact["id"] != memory_id:
            raise MemoryError(
                "error.already_in_scope",
                f"Dieser Text steht schon in {target}.",
                scope=target,
            )
        embedding = self.embedder.embed_many([cleaned])[0]
        updated = self.store.update_text(memory_id, cleaned, embedding, scope=target)
        self._sync(current["scope"], updated["scope"])
        return updated

    def dream(self, scope: str | None = None) -> dict:
        if not self.cfg.llm.enabled:
            return {
                "ok": False,
                "changed": 0,
                "reviewed": 0,
                "promoted": 0,
                "key": "dream.off",
                "message": "KI ist aus. Dreaming hat nichts geändert.",
            }
        resolved = normalize_scope(scope) if scope else ""
        # Dream over every active row. The old 80-row page silently skipped
        # older memories once a scope grew.
        rows = self.store.all_active(resolved or None)
        promotable = [row for row in rows if promotable_daily(row)]
        if len(rows) < 2 and not promotable:
            return {
                "ok": True,
                "changed": 0,
                "reviewed": len(rows),
                "promoted": 0,
                "key": "dream.too_few",
                "message": "Zu wenige Erinnerungen zum Träumen.",
            }
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(row["scope"], []).append(row)
        changed = 0
        reviewed = 0
        promoted_total = 0
        touched: set[str] = set()
        for scope_name, group in groups.items():
            touched.add(scope_name)
            local_reviewed = 0
            merged = 0
            ready = [row for row in group if promotable_daily(row)]
            if len(group) < 2 and not ready:
                reviewed += len(group)
                continue
            if len(group) >= 2:
                for start in range(0, len(group), 30):
                    batch = group[start : start + 30]
                    local_reviewed += len(batch)
                    try:
                        actions = self.llm.dream(scope_name, batch)
                    except LLMError as exc:
                        self._sync(*touched)
                        return {"ok": False, "changed": changed, "reviewed": reviewed + local_reviewed, "message": str(exc)}
                    made = self.apply_actions(actions, scope=scope_name, source="dream", fallback=None)
                    merged += len(made)
                    changed += len(made)
            else:
                local_reviewed = len(group)
            reviewed += local_reviewed
            pairs, scanned = self._near_pairs(scope_name) if len(group) >= 2 else (0, len(group))
            candidates = ready
            reflection = ""
            reflect = getattr(self.llm, "reflect", None)
            if callable(reflect) and (pairs or candidates):
                try:
                    reflection = reflect(scope_name, [row["text"] for row in group[:8]])
                except LLMError:
                    reflection = ""
            promoted = 0
            for row in self.store.all_active(scope_name):
                if not promotable_daily(row):
                    continue
                self.store.set_tier(row["id"], "durable")
                promoted += 1
            promoted_total += promoted
            changed += promoted
            summary = _dream_summary(
                pairs=pairs,
                scanned=scanned,
                candidates=len(candidates),
                reflection=reflection,
                merged=merged,
                promoted=promoted,
                reviewed=local_reviewed,
            )
            self.store.insert_dream(scope_name, "sweep", summary)
        self._sync(*touched)
        return {
            "ok": True,
            "changed": changed,
            "reviewed": reviewed,
            "promoted": promoted_total,
            "key": "dream.done",
            "params": {"changed": changed, "reviewed": reviewed, "promoted": promoted_total},
            "message": f"{changed} Erinnerungen angepasst, {promoted_total} befördert, {reviewed} geprüft.",
        }

    def _near_pairs(self, scope: str, limit_rows: int = 200) -> tuple[int, int]:
        vectors = self.store.vectors_for(scope, include_global=False)[:limit_rows]
        scanned = len(vectors)
        pairs = 0
        for left in range(scanned):
            for right in range(left + 1, scanned):
                if cosine(vectors[left][1], vectors[right][1]) >= 0.86:
                    pairs += 1
                    if pairs >= 12:
                        return pairs, scanned
        return pairs, scanned

    def _sync(self, *scopes: str) -> None:
        try:
            from memoryforge.vault import write_scopes

            write_scopes(self.store, list(scopes) if scopes else None)
        except OSError:
            return

    def _drop_projection(self, scope: str) -> None:
        """Remove the vault directory, then rewrite the index from what remains."""
        from memoryforge.vault import remove_scope, write_index

        try:
            remove_scope(scope)
        finally:
            try:
                write_index(self.store)
            except OSError:
                pass

    def export_rows(self, scope: str | None = None) -> list[dict]:
        resolved = normalize_scope(scope) if scope else ""
        rows = self.store.all_active(resolved or None)
        return [
            {
                "text": row["text"],
                "scope": row["scope"],
                "kind": row["kind"] if row["kind"] in KINDS else "fact",
                "pinned": bool(row["pinned"]),
                "tier": row.get("tier") if row.get("tier") in {"daily", "durable"} else "durable",
            }
            for row in rows
        ]

    def import_rows(self, payload: object) -> dict:
        rows = _import_rows(payload)
        added = 0
        skipped = 0
        previous = self.cfg.llm.enabled
        # Import must not send the archive to the model or rewrite the text.
        self.cfg.llm.enabled = False
        try:
            for item in rows:
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                text = str(item.get("text") or "")
                target = normalize_scope(str(item.get("scope") or "global")) or "global"
                try:
                    result = self.add(text, scope=target, source="import", detect=False)
                except ValueError:
                    skipped += 1
                    continue
                if result["noop"] or not result["memories"]:
                    skipped += 1
                    continue
                row = result["memories"][0]
                kind = item.get("kind")
                if kind in KINDS and kind != row["kind"]:
                    self.store.set_kind(row["id"], kind)
                    row["kind"] = kind
                if item.get("tier") == "daily":
                    self.store.set_tier(row["id"], "daily")
                if item.get("pinned"):
                    self.pin(row["id"], True)
                else:
                    self._sync(row["scope"])
                added += 1
        finally:
            self.cfg.llm.enabled = previous
        return {"added": added, "skipped": skipped}

    def reembed(self) -> int:
        rows = self.store.all_for_reembed()
        if not rows:
            return 0
        vectors = self.embedder.embed_many([row["text"] for row in rows])
        for row, vector in zip(rows, vectors):
            self.store.set_embedding(row["id"], vector)
        return len(rows)


def _import_rows(payload: object) -> list:
    if isinstance(payload, dict):
        if payload.get("format", 1) != 1:
            raise MemoryError("error.import_format", "Unbekanntes Importformat.")
        rows = payload.get("memories")
    elif isinstance(payload, list):
        rows = payload
    else:
        raise MemoryError("error.import_format", "Die Datei enthält keine Erinnerungen.")
    if not isinstance(rows, list):
        raise MemoryError("error.import_format", "Die Datei enthält keine Erinnerungen.")
    if len(rows) > 5000:
        raise MemoryError("error.import_limit", "Höchstens 5000 Erinnerungen auf einmal.")
    return rows


def promotable_daily(row: dict, now: datetime | None = None) -> bool:
    """A daily note may become durable only by copying its existing text."""
    if (row.get("tier") or "durable") != "daily":
        return False
    if row.get("forgotten") or row.get("superseded_by"):
        return False
    if row.get("pinned"):
        return True
    text = (row.get("text") or "").strip()
    if len(text) > 400 or text.count("\n") > 1:
        return False
    age = age_days(row.get("created_at"), now)
    kind = row.get("kind") or "fact"
    recalls = int(row.get("recalls") or 0)
    if kind in {"preference", "decision", "convention"} and age >= 1:
        return True
    if kind == "debug" and recalls >= 2:
        return True
    if kind == "fact" and (recalls >= 2 or age >= 7):
        return True
    return False


def recency_weight(tier: str, pinned: bool, when: str | None, now: datetime | None = None) -> float:
    """Dated daily notes decay. Curated and pinned rows stay evergreen."""
    if pinned or (tier or "durable") != "daily":
        return 1.0
    return 0.5 ** (age_days(when, now) / DAILY_HALF_LIFE_DAYS)


def importance_weight(importance: int | None) -> float:
    try:
        value = int(5 if importance is None else importance)
    except (TypeError, ValueError):
        value = 5
    value = max(1, min(10, value))
    return 0.85 + 0.03 * value


def age_days(value: str | None, now: datetime | None = None) -> float:
    parsed = _parse_time(value)
    if parsed is None:
        return 0.0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current - parsed).total_seconds() / 86400)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _dream_summary(
    *,
    pairs: int,
    scanned: int,
    candidates: int,
    reflection: str,
    merged: int,
    promoted: int,
    reviewed: int,
) -> str:
    rem = f"Model reflection, not a stored fact: {reflection}" if reflection else "REM: no reflection."
    return (
        f"Light: {pairs} near-duplicate pairs in {scanned} rows, {candidates} daily notes ready to promote. "
        f"{rem} "
        f"Deep: {merged} merged, {promoted} promoted verbatim, {reviewed} reviewed. "
        "No new facts were invented."
    )


def _atomic(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 400 or stripped.count("\n") > 1:
        return False
    return len(re.findall(r"[.!?]", stripped)) <= 2


def reset() -> None:
    global _service, _service_key
    with _guard:
        if _service is not None:
            _service.close()
        _service = None
        _service_key = None


def get_service() -> MemoryService:
    global _service, _service_key
    cfg = load_config()
    path = Path(cfg.path) if cfg.path else None
    mtime = path.stat().st_mtime_ns if path and path.exists() else 0
    key = (
        str(path),
        mtime,
        str(db_path()),
        os.environ.get("MEMORYFORGE_EMBED", ""),
        cfg.embed.model,
        cfg.llm.enabled,
        cfg.llm.provider,
        cfg.llm.base_url,
        cfg.llm.model,
        cfg.llm.thinking,
        hash(cfg.llm.api_key),
    )
    with _guard:
        if _service is None or key != _service_key:
            if _service is not None:
                _service.close()
            _service = MemoryService(cfg)
            _service_key = key
        return _service


def seed_demo() -> None:
    service = get_service()
    if service.store.count_active():
        return
    samples = [
        ("global", "Bevorzuge knappe, dauerhafte Fakten statt ganzer Chatverläufe."),
        ("global", "Die Suche läuft lokal. Ein Sprachmodell wird nur beim Schreiben und beim Dreaming benutzt."),
        ("project:github.com/pierelucas/MemoryForge", "MemoryForge speichert Erinnerungen in einer SQLite-Datei auf diesem Rechner."),
        ("project:github.com/pierelucas/MemoryForge", "OpenCode hängt über das MCP-Kommando memoryforge mcp an demselben Speicher."),
    ]
    previous = service.cfg.llm.enabled
    service.cfg.llm.enabled = False
    try:
        for scope, text in samples:
            service.add(text, scope=scope, source="demo")
    finally:
        service.cfg.llm.enabled = previous
