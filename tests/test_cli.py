from typer.testing import CliRunner

import memoryforge.cli as cli
from memoryforge.cli import app


def test_doctor_and_model_list():
    runner = CliRunner()
    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    assert "Version" in doctor.stdout
    models = runner.invoke(app, ["config", "models"])
    assert models.exit_code == 0
    assert "deepseek-flash" in models.stdout
    assert "gpt-4.1-nano" in models.stdout


def test_restore_refuses_while_the_service_still_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_stop", lambda wait=False: False)
    monkeypatch.setattr(cli, "_stop_user_service", lambda: False)
    monkeypatch.setattr(cli, "_wait_stopped", lambda host, port: False)
    restored = []
    monkeypatch.setattr("memoryforge.backup.restore_backup", lambda path: restored.append(path))

    result = CliRunner().invoke(app, ["restore", str(tmp_path / "keep.zip")])
    assert result.exit_code == 1
    assert "läuft noch" in result.output
    assert restored == []
