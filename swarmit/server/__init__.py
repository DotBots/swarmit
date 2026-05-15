"""Unified swarmit-server: one FastAPI backend, two deployment presets.

- Default (shared service): bind 0.0.0.0, JWT auth, JWT records DB.
- `--local`: bind 127.0.0.1, no auth, no DB. Same as the old
  swarmit-daemon, but explicitly opt-in.

The React UI is mounted unconditionally — static files cost nothing
at runtime if no browser asks for them, and a single binary that can
serve both the CLI's `/status` and a browser session is cleaner than
maintaining two near-identical entry points.
"""
