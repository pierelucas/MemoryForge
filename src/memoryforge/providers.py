"""OpenAI-compatible providers and live model catalogs.

Built-in ids are only a fallback. The settings page and `config models --live`
download the provider's own list when a key is available, or without one when
the catalog is public.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

import httpx

from memoryforge import __version__
from memoryforge.paths import data_dir

_SKIP_ID = re.compile(
    r"embed|whisper|tts|dall-?e|moderation|transcri|realtime|rerank|\bclip\b|image-gen|stable-diffusion",
    re.IGNORECASE,
)
_MAX_MODELS = 250


class ProviderError(ValueError):
    """The provider catalog could not be loaded."""


def _provider(
    label: str,
    base_url: str,
    *,
    models: list[dict[str, str]] | None = None,
    models_url: str = "",
    requires_key: bool = True,
    models_public: bool = False,
    supports_thinking: bool = False,
    headers: dict[str, str] | None = None,
) -> dict:
    return {
        "label": label,
        "base_url": base_url,
        "models_url": models_url,
        "requires_key": requires_key,
        "models_public": models_public,
        "supports_thinking": supports_thinking,
        "headers": headers or {},
        "models": models or [],
    }


PROVIDERS: dict[str, dict] = {
    "deepseek": _provider(
        "DeepSeek",
        "https://api.deepseek.com",
        supports_thinking=True,
        models=[
            {"label": "DeepSeek V4.1 Flash", "id": "deepseek-flash"},
            {"label": "DeepSeek V4 Pro", "id": "deepseek-v4-pro"},
        ],
    ),
    "opencode-go": _provider(
        "OpenCode Go",
        "https://opencode.ai/inference/go/openai/v1",
        # The chat base and the catalog live on different paths. Console
        # translates every text model through the OpenAI chat route.
        models_url="https://opencode.ai/inference/go/v1/models",
        models_public=True,
        headers={"x-opencode-session": "memoryforge"},
        models=[
            {"label": "DeepSeek V4.1 Flash", "id": "deepseek-v4.1-flash"},
            {"label": "GLM-5.3-Flash", "id": "glm-5.3-flash"},
        ],
    ),
    "openai": _provider(
        "OpenAI",
        "https://api.openai.com/v1",
        models=[
            {"label": "GPT-4.1 nano", "id": "gpt-4.1-nano"},
            {"label": "GPT-4.1 mini", "id": "gpt-4.1-mini"},
            {"label": "GPT-4o mini", "id": "gpt-4o-mini"},
        ],
    ),
    "openrouter": _provider(
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        models_public=True,
        headers={
            "HTTP-Referer": "http://127.0.0.1:4737",
            "X-Title": "MemoryForge",
        },
    ),
    "xai": _provider("xAI", "https://api.x.ai/v1"),
    "groq": _provider("Groq", "https://api.groq.com/openai/v1"),
    "mistral": _provider("Mistral", "https://api.mistral.ai/v1"),
    "gemini": _provider("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
    "cerebras": _provider("Cerebras", "https://api.cerebras.ai/v1"),
    "together": _provider("Together", "https://api.together.ai/v1"),
    "fireworks": _provider("Fireworks", "https://api.fireworks.ai/inference/v1"),
    "moonshot": _provider("Moonshot", "https://api.moonshot.ai/v1"),
    "dashscope": _provider("Alibaba DashScope", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "github": _provider("GitHub Models", "https://models.github.ai/inference"),
    "huggingface": _provider("Hugging Face", "https://router.huggingface.co/v1"),
    "nvidia": _provider("NVIDIA", "https://integrate.api.nvidia.com/v1"),
    "ollama": _provider("Ollama", "http://127.0.0.1:11434/v1", requires_key=False),
    "ollama-cloud": _provider("Ollama Cloud", "https://ollama.com/v1"),
    "lmstudio": _provider("LM Studio", "http://127.0.0.1:1234/v1", requires_key=False),
    "custom": _provider("OpenAI-compatible", "", requires_key=False),
}


def provider_or_custom(key: str) -> str:
    return key if key in PROVIDERS else "custom"


def model_catalog() -> list[dict[str, str]]:
    """Built-in names plus any catalog already downloaded for a provider."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key, provider in PROVIDERS.items():
        bundled = list(provider["models"]) + cached_models(key)
        for model in bundled:
            model_id = str(model.get("id") or "").strip()
            if not model_id or (key, model_id) in seen:
                continue
            seen.add((key, model_id))
            rows.append(
                {
                    "provider": key,
                    "provider_label": provider["label"],
                    "label": str(model.get("label") or model_id),
                    "id": model_id,
                    "base_url": provider["base_url"],
                }
            )
    return rows


def known_model(model_id: str, provider: str | None = None) -> dict[str, str] | None:
    rows = [row for row in model_catalog() if row["id"] == model_id]
    if provider:
        for row in rows:
            if row["provider"] == provider:
                return row
    return rows[0] if rows else None


def chat_completions_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ProviderError("Keine API-Basis hinterlegt.")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def models_endpoint(provider_key: str, base_url: str) -> str:
    provider = PROVIDERS.get(provider_key) or {}
    default_base = (provider.get("base_url") or "").rstrip("/")
    given = (base_url or "").strip().rstrip("/")
    explicit = provider.get("models_url") or ""
    if explicit and (not given or given == default_base):
        return explicit
    base = given or default_base
    if not base:
        raise ProviderError("Keine API-Basis hinterlegt.")
    if base.endswith("/models"):
        return base
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return f"{base}/models"


def request_headers(provider_key: str, api_key: str) -> dict[str, str]:
    provider = PROVIDERS.get(provider_key) or {}
    headers = {
        "User-Agent": f"MemoryForge/{__version__}",
        "Accept": "application/json",
    }
    headers.update({str(key): str(value) for key, value in (provider.get("headers") or {}).items()})
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def parse_model_list(payload: object) -> list[dict[str, str]]:
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        model_id, label, kind = _model_fields(item)
        if not model_id or model_id in seen:
            continue
        if kind and kind not in {"chat", "model", "llm"}:
            continue
        if _SKIP_ID.search(model_id):
            continue
        seen.add(model_id)
        found.append({"id": model_id, "label": label})
        if len(found) >= _MAX_MODELS:
            break
    found.sort(key=lambda row: row["label"].casefold())
    return found


def fetch_models(provider_key: str, base_url: str, api_key: str = "") -> list[dict[str, str]]:
    """Download chat model ids. Raises ProviderError; never returns the key."""
    url = models_endpoint(provider_key, base_url)
    _check_url(url)
    key = (api_key or "").strip()
    try:
        response = httpx.get(
            url,
            headers=request_headers(provider_key, key),
            timeout=20,
            follow_redirects=not bool(key),
        )
    except httpx.HTTPError as exc:
        raise ProviderError(f"Modellliste nicht erreichbar: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        detail = response.text[:240].replace(key, "[redacted]") if key else response.text[:240]
        raise ProviderError(f"Modellliste {response.status_code}: {detail}")
    if len(response.content) > 2_000_000:
        raise ProviderError("Die Modellliste ist zu groß.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("Die Modellliste ist kein JSON.") from exc
    models = parse_model_list(payload)
    if not models:
        raise ProviderError("Die API hat keine Chat-Modelle geliefert.")
    save_model_cache(provider_key, models)
    return models


def resolve_models(provider_key: str, base_url: str, api_key: str = "") -> tuple[list[dict[str, str]], str, str | None]:
    """Live list, else the last download, else the built-in names."""
    try:
        return fetch_models(provider_key, base_url, api_key), "live", None
    except ProviderError as exc:
        cached = cached_models(provider_key)
        if cached:
            return cached, "cache", str(exc)
        builtin = [
            {"id": row["id"], "label": row["label"]}
            for row in (PROVIDERS.get(provider_key) or {}).get("models", [])
            if row.get("id")
        ]
        if builtin:
            return builtin, "builtin", str(exc)
        raise


def cached_models(provider_key: str) -> list[dict[str, str]]:
    path = _cache_path(provider_key)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("models") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    cleaned = []
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            cleaned.append({"id": str(row["id"]), "label": str(row.get("label") or row["id"])})
    return cleaned


def save_model_cache(provider_key: str, models: list[dict[str, str]]) -> None:
    path = _cache_path(provider_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": models}, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, 0o600)


def _cache_path(provider_key: str):
    safe = re.sub(r"[^a-z0-9._-]", "", (provider_key or "custom").lower()) or "custom"
    return data_dir() / "models" / f"{safe}.json"


def _check_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ProviderError("Die Modell-URL ist ungültig.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderError("Die Modell-URL muss http oder https sein.")
    if parsed.username or parsed.password:
        raise ProviderError("Die Modell-URL darf keine Zugangsdaten enthalten.")


def _model_fields(item: object) -> tuple[str, str, str]:
    if isinstance(item, str):
        text = item.strip()
        return text, text, "chat"
    if not isinstance(item, dict):
        return "", "", ""
    model_id = str(item.get("id") or item.get("model") or "").strip()
    name = str(item.get("name") or "").strip()
    # Ollama's native list uses name as the id and has no separate id.
    if not model_id:
        model_id = name
    kind = str(item.get("type") or "").strip().lower()
    if not kind:
        kind = "chat"
    if name and name != model_id:
        label = f"{name} · {model_id}"
    else:
        label = model_id
    return model_id, label, kind
