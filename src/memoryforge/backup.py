from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import tomli_w

from memoryforge import __version__
from memoryforge.config import load_config
from memoryforge.paths import config_path, data_dir, db_path, ensure_dirs
from memoryforge.service import get_service, reset

ALLOWED = {"manifest.json", "config.toml", "memory.db"}
FORMAT = 1


class BackupError(ValueError):
    pass


def create_backup(dest: Path, *, include_secrets: bool = True) -> Path:
    ensure_dirs()
    service = get_service()
    cfg = load_config()
    stamp_dir = dest.parent
    stamp_dir.mkdir(parents=True, exist_ok=True)
    db_copy = stamp_dir / f".{dest.stem}.memory.db"
    service.store.backup_to(db_copy)
    try:
        manifest = {
            "format": FORMAT,
            "app": "memoryforge",
            "app_version": __version__,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "embed_model": cfg.embed.model,
            "secrets": include_secrets,
        }
        config_text = _config_text(include_secrets)
        if dest.exists():
            dest.unlink()
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("config.toml", config_text)
            archive.write(db_copy, "memory.db")
        # The archive may contain the API key; keep it private.
        os.chmod(dest, 0o600)
    finally:
        if db_copy.exists():
            db_copy.unlink()
    return dest


def restore_backup(archive_path: Path) -> dict:
    if not archive_path.is_file():
        raise BackupError(f"Backup nicht gefunden: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _reject_unsafe(archive)
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (KeyError, json.JSONDecodeError) as exc:
                raise BackupError("manifest.json fehlt oder ist kein JSON.") from exc
            if not isinstance(manifest, dict):
                raise BackupError("manifest.json ist kein Objekt.")
            if manifest.get("format") != FORMAT:
                raise BackupError(
                    f"Unbekanntes Backup-Format {manifest.get('format')!r}. Diese Version liest Format {FORMAT}."
                )
            if "memory.db" not in archive.namelist() or "config.toml" not in archive.namelist():
                raise BackupError("Das Backup enthält nicht config.toml und memory.db.")
            config_bytes = archive.read("config.toml")
            db_bytes = archive.read("memory.db")
    except zipfile.BadZipFile as exc:
        raise BackupError("Das Backup ist kein gültiges ZIP.") from exc
    if not db_bytes.startswith(b"SQLite format 3\x00"):
        raise BackupError("memory.db im Backup ist keine SQLite-Datenbank.")

    reset()
    ensure_dirs()
    config_tmp = config_path().with_suffix(".toml.restore")
    db_tmp = db_path().with_suffix(".db.restore")
    config_tmp.write_bytes(config_bytes)
    db_tmp.write_bytes(db_bytes)
    os.chmod(config_tmp, 0o600)
    os.chmod(db_tmp, 0o600)
    # A stale WAL from the old database can be replayed onto the new file.
    for suffix in ("-wal", "-shm", "-journal"):
        db_path().with_name(db_path().name + suffix).unlink(missing_ok=True)
    config_tmp.replace(config_path())
    db_tmp.replace(db_path())
    config_path().chmod(0o600)
    db_path().chmod(0o600)
    cfg = load_config()
    warning = ""
    if manifest.get("embed_model") and manifest.get("embed_model") != cfg.embed.model:
        warning = (
            f"Embedding-Modell im Backup ist {manifest['embed_model']}, "
            f"lokal ist {cfg.embed.model}. Danach `memoryforge reembed` ausführen."
        )
    return {
        "memories_db": str(db_path()),
        "config": str(config_path()),
        "embed_model": manifest.get("embed_model"),
        "warning": warning,
        "data_dir": str(data_dir()),
    }


def _config_text(include_secrets: bool) -> str:
    path = config_path()
    cfg = load_config()
    if not path.exists():
        cfg.save()
    if include_secrets:
        return config_path().read_text(encoding="utf-8")
    saved = cfg.llm.api_key
    cfg.llm.api_key = ""
    try:
        text = tomli_w.dumps(cfg.to_dict())
    finally:
        cfg.llm.api_key = saved
    return text


def _reject_unsafe(archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        name = info.filename
        if name.endswith("/"):
            raise BackupError(f"Unerwarteter Ordner im Backup: {name}")
        parts = Path(name).parts
        if name.startswith("/") or ".." in parts or name not in ALLOWED:
            raise BackupError(f"Unerwarteter Eintrag im Backup: {name}")
