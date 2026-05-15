# swarmit

## Purpose

Testbed orchestration for robot swarms. Combines (a) an embedded C firmware port for nRF5340 dual-core that uses ARM TrustZone to sandbox user code, with (b) a Python CLI and a FastAPI + React dashboard ("Control Tower") that flash, start/stop, and monitor experiments over a Mari wireless gateway. The TrustZone sandbox guarantees the testbed remains functional even when user firmware is buggy or hostile.

## Tech stack

- **Languages**: C (firmware), Python ≥3.7 (CLI + dashboard backend), TypeScript/React (dashboard frontend)
- **Targets**: Nordic nRF5340 (DotBot v2/v3, nRF5340-DK), nRF52840-DK
- **Frameworks**: Click (CLI); FastAPI + uvicorn + SQLAlchemy + PyJWT (dashboard backend); Vite + Tailwind (frontend)
- **Build**: SEGGER Embedded Studio (`.emProject`) via `emBuild` from `Makefile` + Docker; `hatchling` for Python package; `npm` + Vite for frontend
- **Package**: PyPI as `swarmit`; npm for frontend assets

## Submodules

This repo has **two** git submodules. After cloning, init them:

```bash
git clone --recurse-submodules git@github.com:DotBots/swarmit.git
# or, if already cloned:
git submodule update --init --recursive
```

| Submodule | Path | Pinned (snapshot 2026-05-12) |
|---|---|---|
| `mari` | `mari/` | `v0.8.0-4-g6a27574` |
| `DotBot-libs` | `dotbot-libs/` | `0.1.0-5-g3fce29b` |

**Drift warning**: swarmit's pinned `DotBot-libs` (`0.1.0-5`) is ~41 commits behind what `DotBot-firmware` and `dotbot-lh2-calibration` pin (`0.1.0-46`). API changes in `DotBot-libs` may surface here as build/link failures or stale behavior until the submodule is bumped.

## Entry points

- `swarmit/cli/main.py` — Click CLI; the user-facing flow
- `swarmit/server/main.py` — `swarmit-server` entry point; unified FastAPI backend. Default: shared service (JWT, bind 0.0.0.0, DB on, UI mounted). With `--local`: localhost-only, no auth, no DB
- `swarmit/dashboard/main.py` — deprecated shim; forwards `python -m swarmit.dashboard.main` → `swarmit-server`
- `swarmit/client/` — unified `SwarmitClient` (Protocol + Local + HTTP backends) that every CLI subcommand goes through
- `swarmit/testbed/controller.py` — core orchestration (OTA chunks, start/stop/status)
- `swarmit/testbed/webserver.py` — FastAPI app; shared by all server modes, including `/flash/stream` (SSE per-chunk progress) and `/events` (SSE multiplexing `status` snapshots + `log_event`)
- `device/bootloader/` — TrustZone bootloader; the embedded heart of the sandbox

## Build / run / test

```bash
# Firmware
make bootloader netcore sample
BUILD_TARGET=dotbot-v3 BUILD_CONFIG=Release make docker

# Python
pip install swarmit                  # CLI only
pip install swarmit[dashboard]       # CLI + server
swarmit --help                       # auto-detects swarmit-server on localhost:8001
swarmit --no-server status           # force in-process Controller for this invocation
swarmit-server --local -n 0x1234 &   # local-dev preset (no auth, localhost-only)
swarmit-server -c argus.toml -n 1234 # shared-service preset (JWT, bind 0.0.0.0)

# Tests
tox                                # envs: check, cli, dashboard-cli, tests
# pytest with coverage on swarmit/
cd swarmit/dashboard/frontend && npm ci && npm run typecheck
```

CI: matrix builds for 3 hardware targets × Debug/Release via Docker; multi-OS Python tox; frontend typecheck; automated PyPI release on tags.

## Cross-repo dependencies

- **`mari`** — git submodule at `mari/` (`.gitmodules`); imported throughout `swarmit/testbed/adapter.py`, `protocol.py`, tests
- **`marilib`** — `marilib-pkg >= 0.8.0` in `pyproject.toml:43`
- **`DotBot-libs`** — git submodule at `dotbot-libs/` (`.gitmodules`)
- **`PyDotBot-utils`** — `pydotbot-utils >= 0.3.0` in `pyproject.toml:39`; imported as `dotbot_utils.serial_interface` in `swarmit/cli/main.py:6`
- No references to: `PyDotBot`, `dotbot-lh2-calibration`, `dotbot-provision`, `qrkey`, `DotBot-firmware`

## State of repo (snapshot 2026-05-05)

- Last commit on `main`: 2026-02-27
- Total commits on `main`: 514
- Commits in last 90 days: 5 (cadence dropped sharply)
- Branches:
  - `add-blink-status-led` — 12 months stale, 370 ahead/1 behind. Likely abandoned.
  - `config-net-id-via-flash` — its commits are already on `main`; the branch itself can be deleted.
- TODO/FIXME/XXX/HACK: 6

## Hot spots and known gaps

- **Two parallel bootloaders**: `device/bootloader/` and `device/bootloader-single-core/` plus per-board `.emProject` files at the repo root. Strong consolidation target if board variants converge.
- **Tight coupling to `mari`**: submodule + Python package. `swarmit` and `mari` should likely be released/versioned together.
- Heavy reliance on Mari being available (no fallback transport).

## Branch policy

- Default: `main`
- New work: feature branches off `main`, PRs even for solo work.

## Agent-task ideas

- **Delete `add-blink-status-led`** (12 months stale, 370 commits diverged) and `config-net-id-via-flash` (already on `main`).
- **Consolidate two bootloaders** if board variants allow.
- **Add dashboard frontend tests** (vitest is set up via Vite but no tests authored).
- **Document the Control Tower API** (FastAPI auto-generates schema; expose it as a stable contract).

## Don't

- **Don't change Mari frame formats** without coordinating with `mari/` and `marilib/`.
- **Don't break the TrustZone bootloader's NSC region layout** without verifying every dependent app loader.
- **Don't push the OTA timeout/retry defaults lower** without a 200+ node test — the 725-bot deployment review identified those values as needing to grow with scale, not shrink.
- **Don't commit modifications to `device/bootloader/Source/lh2_calibration.h`** — this file is regenerated locally by `dotbot-calibration-exporter` and contains the operator's per-machine, per-arena calibration. The committed version in `main` is a placeholder / dev value; any change you see in `git status` is local data that must stay local. If `git add .` is about to stage it, exclude it explicitly.
