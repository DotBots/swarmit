"""Unified swarmit-server: one FastAPI backend, two deployment presets.

- Default (shared service): bind 0.0.0.0, JWT auth, JWT records DB.
- `--local`: bind 127.0.0.1, no auth, no DB. Local-dev convenience
  preset so the CLI auto-discovers a fast in-process backend.

The React UI is mounted unconditionally — static files cost nothing
at runtime if no browser asks for them, and a single binary that can
serve both the CLI's `/status` and a browser session is cleaner than
maintaining two near-identical entry points.
"""
