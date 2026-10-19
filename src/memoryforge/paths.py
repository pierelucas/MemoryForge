from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    env = os.environ.get("MEMORYFORGE_CONFIG_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "memoryforge"


def data_dir() -> Path:
    env = os.environ.get("MEMORYFORGE_DATA_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "memoryforge"


def config_path() -> Path:
    return config_dir() / "config.toml"


def db_path() -> Path:
    return data_dir() / "memory.db"


def pid_path() -> Path:
    return data_dir() / "memoryforge.pid"


def log_path() -> Path:
    return data_dir() / "serve.log"


def ensure_dirs() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
