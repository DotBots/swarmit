from swarmit.testbed.helpers import load_toml_config

TEST_CONFIG_TOML = """
adapter = "edge"
serial_port = "/dev/ttyACM0"
baudrate = 1000000
devices = ""
"""


def test_load_toml_config(tmp_path):
    cfg_path = tmp_path / "cfg.toml"
    cfg_path.write_text(TEST_CONFIG_TOML)
    cfg = load_toml_config(str(cfg_path))
    assert cfg["adapter"] == "edge"
    assert cfg["serial_port"] == "/dev/ttyACM0"
    assert cfg["baudrate"] == 1000000
    assert cfg["devices"] == ""


def test_load_toml_config_empty():
    cfg = load_toml_config("")
    assert cfg == {}
