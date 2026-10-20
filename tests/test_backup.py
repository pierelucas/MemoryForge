import json
import zipfile

import pytest

from memoryforge.backup import BackupError, create_backup, restore_backup
from memoryforge.config import load_config
from memoryforge.service import MemoryService, reset


def test_backup_roundtrip_strips_secrets(tmp_path):
    cfg = load_config()
    cfg.llm.api_key = "secret-key-value"
    cfg.llm.model = "deepseek-flash"
    cfg.save()
    service = MemoryService(load_config())
    service.add("Umzugstest merken.", scope="global")
    dest = tmp_path / "move.zip"
    create_backup(dest, include_secrets=False)
    with zipfile.ZipFile(dest) as archive:
        text = archive.read("config.toml").decode()
        manifest = json.loads(archive.read("manifest.json"))
    assert "secret-key-value" not in text
    assert manifest["format"] == 1
    assert manifest["secrets"] is False

    cfg.llm.api_key = "changed"
    cfg.save()
    reset()
    info = restore_backup(dest)
    restored = load_config()
    assert restored.llm.api_key == ""
    assert restored.llm.model == "deepseek-flash"
    assert info["warning"] == ""
    reset()
    found = MemoryService(load_config()).search("Umzugstest", scope="global", include_global=False)
    assert found and "Umzugstest" in found[0]["text"]


def test_backup_file_is_private(tmp_path):
    service = MemoryService(load_config())
    service.add("Privater Umzug.", scope="global")
    dest = tmp_path / "private.zip"
    create_backup(dest, include_secrets=True)
    assert (dest.stat().st_mode & 0o777) == 0o600


def test_restore_rejects_path_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../evil.txt", "nope")
        handle.writestr("manifest.json", json.dumps({"format": 1}))
    with pytest.raises(BackupError):
        restore_backup(archive)


def test_restore_rejects_unknown_format(tmp_path):
    archive = tmp_path / "old.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", json.dumps({"format": 99}))
        handle.writestr("config.toml", "x")
        handle.writestr("memory.db", "x")
    with pytest.raises(BackupError):
        restore_backup(archive)
