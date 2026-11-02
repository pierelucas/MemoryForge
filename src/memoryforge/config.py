from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from memoryforge.paths import config_path, ensure_dirs

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import tomli_w

from memoryforge.i18n import LANGS, normalize_lang
from memoryforge.providers import PROVIDERS, known_model, model_catalog

__all__ = ["PROVIDERS", "known_model", "model_catalog"]

KINDS = ("preference", "decision", "convention", "fact", "debug")


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
class UIConfig:
    lang: str = "en"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    path: object | None = None

    def to_dict(self) -> dict:
        return {
            "server": asdict(self.server),
            "llm": asdict(self.llm),
            "embed": asdict(self.embed),
            "ui": asdict(self.ui),
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
    ui = data.get("ui") or {}
    if not all(isinstance(section, dict) for section in (server, llm, embed, ui)):
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
    cfg.ui.lang = normalize_lang(ui.get("lang"))
    return cfg


def set_value(cfg: Config, key: str, value: str) -> None:
    section, _, field_name = key.partition(".")
    if section not in {"server", "llm", "embed", "ui"} or not field_name:
        raise ValueError("Schlüssel muss wie llm.model aussehen.")
    target = getattr(cfg, section)
    if not hasattr(target, field_name):
        raise ValueError(f"Unbekanntes Feld: {key}")
    if section == "ui" and field_name == "lang":
        text = value.strip().lower()
        if text not in LANGS:
            raise ValueError(f"ui.lang muss {' oder '.join(LANGS)} sein.")
        target.lang = text
        cfg.save()
        return
    if section == "llm" and field_name == "provider":
        key_name = value.strip().lower()
        if key_name not in PROVIDERS:
            known = ", ".join(PROVIDERS)
            raise ValueError(f"Unbekannter Anbieter: {value}. Bekannt: {known}")
        old_default = (PROVIDERS.get(target.provider) or {}).get("base_url") or ""
        new_default = PROVIDERS[key_name].get("base_url") or ""
        target.provider = key_name
        # A switch from the install prompt used to leave the DeepSeek URL in
        # place. Keep a URL the user typed themselves.
        if new_default and (not target.base_url or target.base_url == old_default):
            target.base_url = new_default
        cfg.save()
        return
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
        strip = field_name in {"host", "base_url", "model", "provider", "api_key"}
        setattr(target, field_name, value.strip() if strip else value)
    cfg.save()
