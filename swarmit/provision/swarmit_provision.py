#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import time
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import click

try:
    from .flash_dotbot import flash_nrf_both_cores, flash_nrf_one_core, read_device_id, read_net_id
except ImportError:  # allow running as a script
    from flash_dotbot import flash_nrf_both_cores, flash_nrf_one_core, read_device_id, read_net_id

try:
    from intelhex import IntelHex
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    IntelHex = None
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for older Pythons
    tomllib = None


DEFAULT_BIN_DIR = Path("bin")
VALID_DEVICES = ("dotbot-v3", "gateway")
VALID_PROGRAMMERS = ("jlink", "daplink")
CONFIG_ADDR = 0x0103F800
CONFIG_MAGIC = 0x5753524D

DEVICE_ASSETS: Dict[str, Dict[str, str]] = {
    "dotbot-v3": {
        "app": "bootloader-dotbot-v3.hex",
        "net": "netcore-nrf5340-net.hex",
        "examples": ["rgbled-dotbot-v3.bin", "dotbot-dotbot-v3.bin"],
    },
    "gateway": {
        "app": "03app_gateway_app-nrf5340-app.hex",
        "net": "03app_gateway_net-nrf5340-net.hex",
        "examples": [],
    },
}


def load_config(path: Path) -> dict:
    if tomllib is None:
        raise click.ClickException("tomllib not available; install Python 3.11+ or add tomli.")
    try:
        return tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise click.ClickException(f"Config file not found: {path}") from exc
    except Exception as exc:  # noqa: BLE001 - surface parse errors
        raise click.ClickException(f"Failed to parse config file {path}: {exc}") from exc


def normalize_network_id(raw: Optional[str]) -> Optional[Tuple[int, str]]:
    if raw is None:
        return None
    s = raw.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    try:
        value = int(s, 16)
    except ValueError as exc:
        raise click.ClickException(f"Invalid network_id '{raw}' (expected hex).") from exc
    if not (0x0000 <= value <= 0xFFFF):
        raise click.ClickException("network_id must be 16-bit (0x0000..0xFFFF).")
    return value, f"{value:04X}"


def resolve_fw_root(bin_dir: Path, fw_version: str) -> Path:
    return bin_dir / fw_version


def find_existing_config_hex(fw_root: Path) -> Optional[Path]:
    candidates = sorted(fw_root.glob("config-*.hex"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def make_config_hex_path(fw_root: Path, device: str, fw_version: str, net_id_hex: str) -> Path:
    ts = time.strftime("%Y%b%d-%H%M%S")
    return fw_root / f"config-{device}-{fw_version}-{net_id_hex}-{ts}.hex"


def create_config_hex(dest: Path, net_id_value: int) -> None:
    if IntelHex is None:
        raise click.ClickException("intelhex not available; install it to build config hex.")
    ih = IntelHex()
    for offset, word in enumerate((CONFIG_MAGIC, net_id_value)):
        addr = CONFIG_ADDR + offset * 4
        ih[addr + 0] = (word >> 0) & 0xFF
        ih[addr + 1] = (word >> 8) & 0xFF
        ih[addr + 2] = (word >> 16) & 0xFF
        ih[addr + 3] = (word >> 24) & 0xFF
    dest.parent.mkdir(parents=True, exist_ok=True)
    ih.tofile(str(dest), "hex")


@click.group(help="Swarmit provisioning tool (skeleton).")
def cli() -> None:
    pass


@cli.command("fetch", help="Fetch firmware assets into bin/<fw-version>/ (skeleton).")
@click.option("--fw-version", "-f", required=True, help="Firmware version tag or 'local'.")
@click.option(
    "--local-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="Root directory for local builds (used with --fw-version local).",
)
@click.option(
    "--bin-dir",
    default=DEFAULT_BIN_DIR,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    show_default=True,
    help="Destination bin directory.",
)
def cmd_fetch(fw_version: str, local_root: Optional[Path], bin_dir: Path) -> None:
    if fw_version == "local" and not local_root:
        raise click.ClickException("--local-root is required when --fw-version=local.")
    if fw_version != "local" and local_root:
        click.echo("[WARN] --local-root ignored when --fw-version is not 'local'.", err=True)

    out_dir = resolve_fw_root(bin_dir, fw_version)
    out_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"[INFO] target dir: {out_dir}")

    if fw_version == "local":
        local_root = local_root.expanduser().resolve()
        mapping = {
            "bootloader-dotbot-v3.hex": local_root
            / "device/bootloader/Output/dotbot-v3/Debug/Exe/bootloader-dotbot-v3.hex",
            "netcore-nrf5340-net.hex": local_root
            / "device/network_core/Output/nrf5340-net/Debug/Exe/netcore-nrf5340-net.hex",
            "03app_gateway_app-nrf5340-app.hex": local_root
            / "mari/app/03app_gateway_app/Output/nrf5340-app/Debug/Exe/03app_gateway_app-nrf5340-app.hex",
            "03app_gateway_net-nrf5340-net.hex": local_root
            / "mari/app/03app_gateway_net/Output/nrf5340-net/Debug/Exe/03app_gateway_net-nrf5340-net.hex",
        }

        missing = [name for name, src in mapping.items() if not src.exists()]
        if missing:
            missing_list = ", ".join(missing)
            raise click.ClickException(f"Missing local build artifacts: {missing_list}")

        for name, src in mapping.items():
            dest = out_dir / name
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            try:
                os.symlink(src, dest)
                click.echo(f"[LINK] {dest} -> {src}")
            except OSError:
                shutil.copy2(src, dest)
                click.echo(f"[COPY] {dest} <- {src}")
        return

    click.echo("[TODO] download assets from GitHub releases for remote versions")


@cli.command("flash", help="Flash firmware + config using versioned bin layout (skeleton).")
@click.option("--device", "-d", type=click.Choice(VALID_DEVICES), required=True)
@click.option("--fw-version", "-f", help="Firmware version tag or 'local'.")
@click.option("--network-id", "-n", help="16-bit hex network ID, e.g. 0100.")
@click.option("--config", "config_path", type=click.Path(path_type=Path, dir_okay=False))
@click.option(
    "--bin-dir",
    default=DEFAULT_BIN_DIR,
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    show_default=True,
    help="Bin directory containing firmware files.",
)
def cmd_flash(
    device: str,
    fw_version: Optional[str],
    network_id: Optional[str],
    config_path: Optional[Path],
    bin_dir: Path,
) -> None:
    config = {}
    if config_path:
        config = load_config(config_path)

    provisioning = config.get("provisioning", {}) if isinstance(config, dict) else {}
    fw_version = fw_version or provisioning.get("firmware_version")
    net_raw = network_id or provisioning.get("network_id")

    if not fw_version:
        raise click.ClickException("Missing --fw-version (or provisioning.firmware_version in config).")
    net_id = normalize_network_id(net_raw)
    if net_id is None:
        raise click.ClickException("Missing --network-id (or provisioning.network_id in config).")

    net_id_val, net_id_hex = net_id
    fw_root = resolve_fw_root(bin_dir, fw_version)
    if not fw_root.exists():
        raise click.ClickException(f"Firmware root not found: {fw_root}")
    assets = DEVICE_ASSETS[device]

    app_hex = fw_root / assets["app"]
    net_hex = fw_root / assets["net"]
    config_hex = find_existing_config_hex(fw_root)
    if config_hex is not None:
        click.secho(f"[NOTE] using existing config hex: {config_hex}", fg="yellow")
    else:
        config_hex = make_config_hex_path(fw_root, device, fw_version, net_id_hex)
        click.secho(f"[INFO] created new config hex: {config_hex}", fg="green")

    missing = [str(p) for p in (app_hex, net_hex) if not p.exists()]
    if missing:
        missing_list = ", ".join(missing)
        raise click.ClickException(f"Missing firmware files: {missing_list}")

    click.echo(f"[INFO] device: {device}")
    click.echo(f"[INFO] fw_version: {fw_version}")
    click.echo(f"[INFO] network_id: 0x{net_id_hex}")
    click.echo(f"[INFO] app hex: {app_hex}")
    click.echo(f"[INFO] net hex: {net_hex}")
    click.echo(f"[INFO] config hex: {config_hex}")

    if not config_hex.exists():
        create_config_hex(config_hex, net_id_val)
        click.echo(f"[OK  ] wrote config hex: {config_hex}")
    else:
        click.echo(f"[INFO] using existing config hex: {config_hex}")
    flash_nrf_both_cores(app_hex, net_hex, nrfjprog_opt=None, snr_opt=None)
    flash_nrf_one_core(net_hex=config_hex, nrfjprog_opt=None, snr_opt=None)
    click.echo(f"\n[INFO] ==== Flash Complete ====\n")
    try:
        readback_net_id = read_net_id()
        readback_device_id = read_device_id()
    except RuntimeError as exc:
        click.echo(f"[WARN] readback failed: {exc}", err=True)
        return
    click.echo(f"[INFO] readback net_id: {readback_net_id}")
    click.echo(f"[INFO] readback device_id: {readback_device_id}")


@cli.command("flash-hex", help="Flash explicit app/net hex files (skeleton).")
@click.option("--app", "app_hex", type=click.Path(path_type=Path, dir_okay=False))
@click.option("--net", "net_hex", type=click.Path(path_type=Path, dir_okay=False))
def cmd_flash_hex(app_hex: Optional[Path], net_hex: Optional[Path]) -> None:
    if not app_hex and not net_hex:
        raise click.ClickException("Provide at least one of --app or --net.")
    if app_hex:
        click.echo(f"[TODO] flash app core: {app_hex}")
    if net_hex:
        click.echo(f"[TODO] flash net core: {net_hex}")


@cli.command("read-config", help="Read config from the device (skeleton).")
def cmd_read_config() -> None:
    try:
        readback_net_id = read_net_id()
        readback_device_id = read_device_id()
    except RuntimeError as exc:
        click.echo(f"[WARN] readback failed: {exc}", err=True)
        return
    click.echo(f"[INFO] readback net_id: {readback_net_id}")
    click.echo(f"[INFO] readback device_id: {readback_device_id}")


@cli.command("flash-bringup", help="Flash J-Link OB or DAPLink programmer (skeleton).")
@click.option("--programmer", "-p", type=click.Choice(VALID_PROGRAMMERS), required=True)
@click.option(
    "--files-dir",
    "-d",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    required=True,
)
def cmd_flash_bringup(programmer: str, files_dir: Path) -> None:
    files_dir = files_dir.expanduser().resolve()
    if not files_dir.exists():
        raise click.ClickException(f"files-dir does not exist: {files_dir}")

    required = {
        "jlink": ["JLink-ob.bin", "stm32f103xb_bl.hex"],
        "daplink": ["stm32f103xb_bl.hex", "stm32f103xb_if.hex"],
    }[programmer]

    missing = [name for name in required if not (files_dir / name).exists()]
    if missing:
        missing_list = ", ".join(missing)
        raise click.ClickException(f"Missing required files in {files_dir}: {missing_list}")

    click.echo(f"[INFO] programmer: {programmer}")
    click.echo(f"[INFO] files-dir: {files_dir}")
    click.echo("[TODO] flash programmer firmware using J-Link / pyOCD flow")


def main() -> int:
    cli(standalone_mode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
