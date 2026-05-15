"""Smoke tests for the swarmit-daemon entry point."""

from click.testing import CliRunner

from swarmit.service.main import main


def test_service_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "swarmit daemon" in result.output.lower()
    assert "--bind-host" in result.output
    assert "--http-port" in result.output


def test_service_refuses_non_localhost_bind():
    """Daemon must refuse non-127.0.0.1 binds while auth is off."""
    runner = CliRunner()
    result = runner.invoke(main, ["--bind-host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "refusing to start" in result.output.lower()


def test_service_refuses_lan_ip_bind():
    runner = CliRunner()
    result = runner.invoke(main, ["--bind-host", "192.168.1.5"])
    assert result.exit_code != 0
    assert "refusing to start" in result.output.lower()
