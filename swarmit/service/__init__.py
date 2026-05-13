"""Standalone swarmit daemon: the dashboard backend without the React UI.

Runs the same FastAPI app as the dashboard, exposing /status, /flash,
/start, /stop, /settings (and the new endpoints added in Phase B). The
CLI auto-detects this daemon when running and routes its commands
through it instead of building a fresh Controller per invocation.
"""
