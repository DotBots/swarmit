"""Hatch custom hook module."""

# pylint: disable=too-few-public-methods

import os
import shlex
import subprocess
import sys

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

NPM_INSTALL_CMD = "npm install --no-progress"
NPM_BUILD_CMD = "npm run build"


def build_frontend(root):
    """Builds the ReactJS frontend."""
    frontend_dir = os.path.join(root, "swarmit", "dashboard", "frontend")
    os.makedirs(os.path.join(frontend_dir, "dist"), exist_ok=True)

    if sys.platform != "win32":
        print("Building React frontend application...")
        subprocess.run(
            shlex.split(NPM_INSTALL_CMD), cwd=frontend_dir, check=True
        )
        subprocess.run(
            shlex.split(NPM_BUILD_CMD), cwd=frontend_dir, check=True
        )


class CustomBuildHook(BuildHookInterface):
    """Custom build hook that will build the React dashboard frontend."""

    def initialize(self, _, __):
        """Will be called before creating the source archive."""
        if os.getenv("SKIP_SDIST_HOOK") is not None:
            return
        build_frontend(self.root)
