from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from memoryforge.paths import config_path, ensure_dirs

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import tomli_w

PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "supports_thinking": True,
        "models": [
            {"label": "DeepSeek V4.1 Flash", "id": "deepseek-flash"},
            {"label": "DeepSeek V4 Pro", "id": "deepseek-v4-pro"},
        ],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "supports_thinking": False,
        "models": [
            {"label": "GPT-4.1 nano", "id": "gpt-4.1-nano"},
            {"label": "GPT-4.1 mini", "id": "gpt-4.1-mini"},
            {"label": "GPT-4o mini", "id": "gpt-4o-mini"},
        ],
    },
    "custom": {
        "label": "OpenAI-kompatibel",
        "base_url": "",
        "supports_thinking": True,
        "models": [],
    },
}

KINDS = ("preference", "decision", "convention", "fact", "debug")
KIND_LABELS = {
    "preference": "Vorliebe",
    "decision": "Entscheidung",
    "convention": "Konvention",
    "fact": "Fakt",
    "debug": "Debug",
}


def model_catalog() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, provider in PROVIDERS.items():
        for model in provider["models"]:
            rows.append(
                {
                    "provider": key,
                    "provider_label": provider["label"],
                    "label": model["label"],
                    "id": model["id"],
                    "base_url": provider["base_url"],
                }
            )
    return rows


def known_model(model_id: str) -> dict[str, str] | None:
    for row in model_catalog():
        if row["id"] == model_id:
            return row
    return None


@dataclass
class ServerConfig:
    autostart: bool = False
    host: str = "127.0.0.1"
    port: int = 4737
    open_browser: bool = False


@dataclass
class LLMConfig:
    enabled: bool = False
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    thinking: bool = False
    api_key: str = ""


@dataclass
class EmbedConfig:
    model: str = "BAAI/bge-small-en-v1.5"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    path: object | None = None

    def to_dict(self) -> dict:
        return {
            "server": asdict(self.server),
            "llm": asdict(self.llm),
            "embed": asdict(self.embed),
        }

    def masked(self) -> dict:
        data = self.to_dict()
        key = data["llm"]["api_key"]
        data["llm"]["api_key"] = ("****" + key[-4:]) if key else ""
        return data

    def save(self) -> None:
        from pathlib import Path

        path = Path(self.path) if self.path else config_path()
        ensure_dirs()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomli_w.dumps(self.to_dict()), encoding="utf-8")
        os.chmod(path, 0o600)
        self.path = path


def coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "ja", "on", "an"}:
        return True
    if text in {"0", "false", "no", "nein", "off", "aus"}:
        return False
    return default


class ConfigError(ValueError):
    """The config file exists but cannot be used."""


def load_config() -> Config:
    path = config_path()
    cfg = Config(path=path)
    if not path.exists():
        return cfg
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"Konfiguration {path} ist nicht lesbar: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Konfiguration {path} enthält keine Tabelle.")
    server = data.get("server") or {}
    llm = data.get("llm") or {}
    embed = data.get("embed") or {}
    if not all(isinstance(section, dict) for section in (server, llm, embed)):
        raise ConfigError(f"Konfiguration {path} enthält einen ungültigen Abschnitt.")
    cfg.server.autostart = coerce_bool(server.get("autostart"), False)
    cfg.server.host = str(server.get("host") or "127.0.0.1")
    try:
        port = int(server.get("port") or 4737)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"server.port in {path} ist keine Zahl.") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(f"server.port in {path} liegt außerhalb von 1 bis 65535.")
    cfg.server.port = port
    cfg.server.open_browser = coerce_bool(server.get("open_browser"), False)
    cfg.llm.enabled = coerce_bool(llm.get("enabled"), False)
    cfg.llm.provider = str(llm.get("provider") or "deepseek")
    default_url = PROVIDERS.get(cfg.llm.provider, {}).get("base_url") or ""
    cfg.llm.base_url = str(llm.get("base_url") if llm.get("base_url") is not None else default_url)
    cfg.llm.model = str(llm.get("model") or "deepseek-flash")
    cfg.llm.thinking = coerce_bool(llm.get("thinking"), False)
    cfg.llm.api_key = str(llm.get("api_key") or "")
    cfg.embed.model = str(embed.get("model") or "BAAI/bge-small-en-v1.5")
    return cfg


def set_value(cfg: Config, key: str, value: str) -> None:
    section, _, field_name = key.partition(".")
    if section not in {"server", "llm", "embed"} or not field_name:
        raise ValueError("Schlüssel muss wie llm.model aussehen.")
    target = getattr(cfg, section)
    if not hasattr(target, field_name):
        raise ValueError(f"Unbekanntes Feld: {key}")
    current = getattr(target, field_name)
    if isinstance(current, bool):
        setattr(target, field_name, coerce_bool(value))
    elif isinstance(current, int) and not isinstance(current, bool):
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} erwartet eine Zahl, nicht {value!r}.") from exc
        if section == "server" and field_name == "port" and not 1 <= number <= 65535:
            raise ValueError("server.port muss zwischen 1 und 65535 liegen.")
        setattr(target, field_name, number)
    else:
        if section == "server" and field_name == "host" and not value.strip():
            raise ValueError("server.host darf nicht leer sein.")
        setattr(target, field_name, value.strip() if field_name in {"host", "base_url", "model", "provider"} else value)
    cfg.save()
