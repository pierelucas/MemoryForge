from __future__ import annotations

import hashlib
import math
import os
import re
import threading


class Embedder:
    name = "base"

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Deterministic local vectors. Tests and the offline fallback use this."""

    name = "hash"
    dim = 64

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embed(text) for text in texts]


class FastEmbedder(Embedder):
    name = "fastembed"

    def __init__(self, model: str) -> None:
        self.model = model
        self.name = f"fastembed:{model}"
        self._model = None
        self._lock = threading.Lock()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=self.model)
            vectors = list(self._model.embed(texts))
        return [[float(x) for x in vector] for vector in vectors]


_warned = False


def get_embedder(model: str) -> Embedder:
    global _warned
    mode = os.environ.get("MEMORYFORGE_EMBED", "fastembed").strip().lower()
    if mode == "hash":
        return HashEmbedder()
    try:
        return FastEmbedder(model)
    except Exception:
        if not _warned:
            _warned = True
            print(
                "MemoryForge: fastembed ist nicht verfügbar, suche mit dem Hash-Fallback. "
                "Für semantische Suche fastembed installieren (ist in den Abhängigkeiten enthalten)."
            )
        return HashEmbedder()


def _hash_embed(text: str) -> list[float]:
    tokens = re.findall(r"\w+", text.lower(), flags=re.UNICODE) or [text.lower()]
    vec = [0.0] * HashEmbedder.dim
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index, byte in enumerate(digest):
            vec[index % HashEmbedder.dim] += (byte - 128) / 128.0
    norm = math.sqrt(sum(value * value for value in vec)) or 1.0
    return [value / norm for value in vec]
