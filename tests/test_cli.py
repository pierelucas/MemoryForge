from typer.testing import CliRunner

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
