"""Smoke tests for the swarmit-server entry point and its deprecation shim."""

import sys
from unittest.mock import patch

from click.testing import CliRunner

from swarmit.server.main import main


def test_server_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "swarmit FastAPI backend" in result.output
    assert "--local" in result.output
    assert "--bind-host" in result.output
    assert "--http-port" in result.output


def test_server_local_refuses_non_localhost_bind():
    """With --local (auth off), refuse 0.0.0.0 or any LAN address."""
    runner = CliRunner()
    result = runner.invoke(main, ["--local", "--bind-host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "refusing to start" in result.output.lower()


def test_server_local_refuses_lan_ip_bind():
    runner = CliRunner()
    result = runner.invoke(main, ["--local", "--bind-host", "192.168.1.5"])
    assert result.exit_code != 0
    assert "refusing to start" in result.output.lower()


def test_daemon_shim_injects_local():
    """`swarmit-daemon` entry should prepend --local before forwarding."""
    from swarmit.service import main as svc_mod

    captured: dict = {}

    def _fake_server_main():
        captured["argv"] = list(sys.argv)

    saved_argv = sys.argv
    sys.argv = ["swarmit-daemon", "--help"]
    try:
        with patch("swarmit.server.main.main", side_effect=_fake_server_main):
            svc_mod.main()
    finally:
        sys.argv = saved_argv

    assert captured["argv"][1] == "--local"
