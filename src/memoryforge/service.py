from __future__ import annotations

import os
import re
import threading
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
            return {"memories": [memory], "noop": False, "llm": False}

        try:
            actions = self.llm.extract(cleaned, resolved, neighbors[:5])
        except LLMError:
            memory = self._insert(cleaned, resolved, "fact", source, confidence=0.5)
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

    def _insert(self, text: str, scope: str, kind: str, source: str, confidence: float) -> dict:
        embedding = self.embedder.embed_many([text])[0]
        return self.store.insert(
            text=text,
            scope=scope,
            kind=kind,
            source=source,
            embedding=embedding,
            confidence=confidence,
        )

    def search(self, query: str, *, scope: str | None = None, limit: int = 8, include_global: bool | None = None) -> list[dict]:
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
            if row["pinned"]:
                score += 0.04
            shown = dict(row)
            shown["score"] = round(score, 4)
            results.append(shown)
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def brief(self, scope: str | None = None, *, detect: bool = False) -> dict:
        resolved = normalize_scope(scope) if scope else ""
        if not resolved and detect:
            resolved = detect_scope()
        include_global = bool(resolved) and resolved != "global"
        pinned = self.store.list_memories(scope=resolved or None, include_global=include_global, limit=8, pinned_only=True)
        recent = self.store.list_memories(scope=resolved or None, include_global=include_global, limit=12)
        seen = {item["id"] for item in pinned}
        memories = pinned + [item for item in recent if item["id"] not in seen]
        return {"scope": resolved or "all", "memories": memories[:12]}

    def list_memories(self, scope: str | None = None, limit: int = 50) -> list[dict]:
        resolved = normalize_scope(scope) if scope else ""
        return self.store.list_memories(scope=resolved or None, include_global=False, limit=clamp_limit(limit))

    def forget(self, memory_id: str) -> None:
        self.store.forget(memory_id)

    def forget_scope(self, scope: str) -> int:
        resolved = normalize_scope(scope)
        if not resolved:
            raise MemoryError("error.invalid_scope", "Ungültiger Scope.")
        return self.store.forget_scope(resolved)

    def pin(self, memory_id: str, pinned: bool = True) -> dict:
        return self.store.set_pinned(memory_id, pinned)

    def update(self, memory_id: str, text: str, scope: str | None = None) -> dict:
        current = self.store.get(memory_id)
        if current is None:
            raise KeyError(memory_id)
        cleaned = redact(text)
        if not cleaned:
            raise MemoryError("error.empty_text", "Leerer Text.")
        target = normalize_scope(scope) if scope else current["scope"]
        if not target:
            raise MemoryError("error.invalid_scope", "Ungültiger Scope.")
        if target != current["scope"] and current["forgotten"]:
            raise MemoryError(
                "error.forgotten_move",
                "Vergessene Erinnerungen lassen sich nicht verschieben.",
            )
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
        return self.store.update_text(memory_id, cleaned, embedding, scope=target)

    def dream(self, scope: str | None = None) -> dict:
        if not self.cfg.llm.enabled:
            return {
                "ok": False,
                "changed": 0,
                "reviewed": 0,
                "key": "dream.off",
                "message": "KI ist aus. Dreaming hat nichts geändert.",
            }
        resolved = normalize_scope(scope) if scope else ""
        # Dream over every active row. The old 80-row page silently skipped
        # older memories once a scope grew.
        rows = self.store.all_active(resolved or None)
        if len(rows) < 2:
            return {
                "ok": True,
                "changed": 0,
                "reviewed": len(rows),
                "key": "dream.too_few",
                "message": "Zu wenige Erinnerungen zum Träumen.",
            }
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(row["scope"], []).append(row)
        changed = 0
        reviewed = 0
        for scope_name, group in groups.items():
            if len(group) < 2:
                reviewed += len(group)
                continue
            for start in range(0, len(group), 30):
                batch = group[start : start + 30]
                reviewed += len(batch)
                try:
                    actions = self.llm.dream(scope_name, batch)
                except LLMError as exc:
                    return {"ok": False, "changed": changed, "reviewed": reviewed, "message": str(exc)}
                made = self.apply_actions(actions, scope=scope_name, source="dream", fallback=None)
                changed += len(made)
        return {
            "ok": True,
            "changed": changed,
            "reviewed": reviewed,
            "key": "dream.done",
            "params": {"changed": changed, "reviewed": reviewed},
            "message": f"{changed} Erinnerungen angepasst, {reviewed} geprüft.",
        }

    def reembed(self) -> int:
        rows = self.store.all_for_reembed()
        if not rows:
            return 0
        vectors = self.embedder.embed_many([row["text"] for row in rows])
        for row, vector in zip(rows, vectors):
            self.store.set_embedding(row["id"], vector)
        return len(rows)


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
    key = (str(path), mtime, str(db_path()), os.environ.get("MEMORYFORGE_EMBED", ""), cfg.embed.model, cfg.llm.enabled, cfg.llm.model)
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
