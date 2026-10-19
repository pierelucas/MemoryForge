import pytest


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORYFORGE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MEMORYFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMORYFORGE_EMBED", "hash")
    monkeypatch.delenv("MEMORYFORGE_DEMO", raising=False)
    from memoryforge.service import reset

    reset()
    yield
    reset()
