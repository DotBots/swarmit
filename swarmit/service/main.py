#!/usr/bin/env python
"""Deprecated alias for `swarmit-server --local`.

Kept for one release as a backward-compat shim. Prefer the unified
`swarmit-server` entry point.
"""

import sys


def main():
    sys.stderr.write(
        "[deprecated] `swarmit-daemon` is an alias for "
        "`swarmit-server --local`; switch when convenient.\n"
    )
    # Inject --local before any user-supplied args so the daemon preset
    # (localhost, no auth, no DB) is preserved transparently.
    sys.argv.insert(1, "--local")
    from swarmit.server.main import main as server_main

    server_main()


if __name__ == "__main__":
    main()
