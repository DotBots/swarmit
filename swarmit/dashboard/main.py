#!/usr/bin/env python
"""Deprecated module; prefer `swarmit-server`.

Kept for backward compatibility with `python -m swarmit.dashboard.main`
in operator scripts and the older README. Forwards all args to
`swarmit-server` (which mounts the React UI by default).
"""

import sys


def main():
    sys.stderr.write(
        "[deprecated] `python -m swarmit.dashboard.main` is an alias for "
        "`swarmit-server`; switch when convenient.\n"
    )
    from swarmit.server.main import main as server_main

    server_main()


if __name__ == "__main__":
    main()
