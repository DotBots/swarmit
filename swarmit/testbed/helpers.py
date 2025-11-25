import tomllib


def load_toml_config(path):
    if not path:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)
