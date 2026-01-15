#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import click

# Timings
POLL_INTERVAL = 1.0
TIMEOUT_JLINK_SEC = 120
TIMEOUT_BUILD_SEC = 900
TIMEOUT_MAINTENANCE_SEC = 300

DEFAULT_SWD_SPEED_KHZ = 4000


def run(cmd, timeout=None, cwd=None):
    print(f"[CMD] {' '.join(cmd)}")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout, cwd=cwd)
    print(proc.stdout)
    return proc.returncode, proc.stdout


def run_capture(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or f"Command failed: {' '.join(cmd)}")
    return proc.stdout


def which_tool(exe_name, user_supplied=None, candidates=None):
    if user_supplied:
        return user_supplied
    p = shutil.which(exe_name)
    if p:
        return p
    for c in (candidates or []):
        if Path(c).exists():
            return c
    return exe_name


# ---------- JLink / DAPLink (APM32F103) ----------
def make_jlink_script(device, speed_khz, hex_path):
    lines = []
    lines.append(f"device {device}")
    lines.append("si SWD")
    if speed_khz:
        lines.append(f"speed {speed_khz}")
    lines.append("connect")
    lines.append("h")
    lines.append("r")
    lines.append("erase")
    lines.append(f"loadfile {hex_path}")
    lines.append("verify")
    lines.append("r")
    lines.append("g")
    lines.append("exit")
    return "\n".join(lines)


def jlink_flash_hex(jlink_exe, device, image_hex, timeout=TIMEOUT_JLINK_SEC):
    speed_khz = DEFAULT_SWD_SPEED_KHZ
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jlink") as tf:
        tf.write(make_jlink_script(device, speed_khz, str(image_hex)))
        script_path = tf.name
    try:
        rc, out = run([jlink_exe, "-CommanderScript", script_path], timeout=timeout)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
    if rc != 0 or "ERROR" in out.upper() or "FAILED" in out.upper():
        raise RuntimeError("J-Link flash failed; see log above.")


def pyocd_flash_hex(jlink_bin, device):
    erase_args = [
        "pyocd",
        "erase",
        "--chip",
        "--pack",
        "Geehy.APM32F1xx_DFP.1.1.0.pack",
        "-t",
        str(device),
        "--uid",
        "261006773",
    ]
    rc, out = run(erase_args, timeout=60)
    args = ["pyocd", "flash", str(jlink_bin)]
    args += ["--pack", "Geehy.APM32F1xx_DFP.1.1.0.pack"]
    args += ["-t", str(device)]
    rc, out = run(args, timeout=120)


def do_daplink(bl_hex: Path, apm_device: str, jlinktool: str | None):
    """Flash STM32 bootloader (DAPLink) using external J-Link."""
    jlink_tool = which_tool(
        "JLink.exe",
        jlinktool,
        candidates=[
            # r"C:\Program Files\SEGGER\JLink_V818\JLink.exe",
            "/usr/local/bin/JLinkExe",
        ],
    )
    if not bl_hex.exists():
        raise FileNotFoundError(f"Bootloader image not found: {bl_hex}")

    print("== Flashing STM32 bootloader (DAPLink) to APM32F103CB ==")
    jlink_flash_hex(jlink_tool, apm_device, bl_hex)
    print("[OK] DAPLink bootloader programmed.")


def do_daplink_if(if_hex: Path, apm_device: str):
    """Flash DAPLink interface firmware over SWD using pyOCD."""
    if not if_hex.exists():
        raise FileNotFoundError(f"DAPLink interface image not found: {if_hex}")

    print("== Flashing DAPLink interface image via pyOCD ==")
    pyocd_flash_hex(if_hex, apm_device)
    print("[OK] DAPLink interface programmed.")


def do_jlink(jlink_bin: Path, bl_hex: Path, apm_device: str, jlinktool: str | None):
    """Flash STM32 bootloader, then J-Link OB image (overwrites BL)."""
    if not jlink_bin.exists():
        raise FileNotFoundError(f"J-Link OB image not found: {jlink_bin}")

    do_daplink(bl_hex=bl_hex, apm_device=apm_device, jlinktool=jlinktool)

    print("[INFO] Waiting 5 seconds for STM32 bootloader to enumerate...")
    time.sleep(5)

    print("== Flashing J-Link OB image via pyOCD ==")
    pyocd_flash_hex(jlink_bin, apm_device)
    print("[OK] J-Link OB programmed.")


# ---------- Flash nRF5340 with nrfjprog ----------
def pick_last_jlink_snr(nrfjprog_opt=None):
    nrfjprog = which_tool("nrfjprog.exe", nrfjprog_opt, candidates=[
        # r"C:\Program Files\Nordic Semiconductor\nrf-command-line-tools\bin\nrfjprog.exe"
        "/usr/local/bin/nrfjprog",
    ])

    rc2, out2 = run([nrfjprog, "--ids"], timeout=10)
    ids = [l.strip() for l in out2.splitlines() if l.strip().isdigit()] if rc2 == 0 else []
    print(f"[DEBUG] Found J-Link IDs: {ids}")
    if ids:
        return ids[-1]
    raise RuntimeError("Unable to auto-select J-Link; provide --snr explicitly.")


def nrfjprog_recover(nrfjprog, snr=None):
    args = [nrfjprog, "-f", "NRF53"]
    if snr:
        args += ["-s", str(snr)]
    print(f"[INFO] Recovering both cores of nRF5340 (SNR={snr})...")
    rc, out = run(args + ["--recover", "--coprocessor", "CP_APPLICATION"], timeout=120)
    rc, out = run(args + ["--recover", "--coprocessor", "CP_NETWORK"], timeout=120)
    print(f"[INFO] Erasing both cores of nRF5340 (SNR={snr})...")
    rc, out = run(args + ["-e"], timeout=120)


def nrfjprog_program(nrfjprog, hex_path, network=False, verify=True, reset=True, chiperase=True, snr=None):
    args = [nrfjprog, "-f", "NRF53"]
    if snr:
        args += ["-s", str(snr)]
    if network:
        args += ["--coprocessor", "CP_NETWORK"]
    else:
        args += ["--coprocessor", "CP_APPLICATION"]
    args += ["--program", str(hex_path)]
    if verify:
        args += ["--verify"]
    if chiperase:
        args += ["--chiperase"]
    if reset:
        args += ["--reset"]
    rc, out = run(args, timeout=120)
    if rc != 0 or "ERROR" in out.upper() or "failed" in out.lower():
        raise RuntimeError("nrfjprog programming failed; see log above.")


def _parse_memrd_words(output: str) -> list[str]:
    line = output.strip().splitlines()[0] if output.strip() else ""
    if ":" not in line:
        raise RuntimeError(f"Unexpected memrd output: {output.strip()}")
    _, rest = line.split(":", 1)
    words = [w for w in rest.strip().split() if not w.startswith(("0x", "0X"))]
    return words


def read_device_id() -> str:
    nrfjprog = which_tool(
        "nrfjprog.exe",
        candidates=[
            # r"C:\Program Files\Nordic Semiconductor\nrf-command-line-tools\bin\nrfjprog.exe"
            "/usr/local/bin/nrfjprog",
        ],
    )
    out = run_capture(
        [nrfjprog, "-f", "NRF53", "--coprocessor", "CP_NETWORK", "--memrd", "0x01FF0204", "--n", "8"]
    )
    words = _parse_memrd_words(out)
    if len(words) < 2:
        raise RuntimeError(f"Unexpected device ID output: {out.strip()}")
    return f"{words[1]}{words[0]}"


def read_net_id() -> str:
    nrfjprog = which_tool(
        "nrfjprog.exe",
        candidates=[
            # r"C:\Program Files\Nordic Semiconductor\nrf-command-line-tools\bin\nrfjprog.exe"
            "/usr/local/bin/nrfjprog",
        ],
    )
    out = run_capture(
        [nrfjprog, "-f", "NRF53", "--coprocessor", "CP_NETWORK", "--memrd", "0x0103F804", "--n", "4"]
    )
    words = _parse_memrd_words(out)
    if len(words) < 1:
        raise RuntimeError(f"Unexpected net ID output: {out.strip()}")
    return f"{words[0][-4:]}"


def flash_nrf_both_cores(app_hex: Path, net_hex: Path, nrfjprog_opt: str | None, snr_opt: str | None):
    """Flash nRF5340 application and network cores with full recover + chiperase."""
    if not app_hex.exists():
        raise FileNotFoundError(f"App hex not found: {app_hex}")
    if not net_hex.exists():
        raise FileNotFoundError(f"Net hex not found: {net_hex}")

    nrfjprog = which_tool(
        "nrfjprog.exe",
        nrfjprog_opt,
        candidates=[
            # r"C:\Program Files\Nordic Semiconductor\nrf-command-line-tools\bin\nrfjprog.exe"
            "/usr/local/bin/nrfjprog",
        ],
    )

    snr = snr_opt or pick_last_jlink_snr(nrfjprog)
    print(f"[INFO] Using J-Link with serial number: {snr}")

    nrfjprog_recover(nrfjprog, snr=snr)

    print("== Flashing nRF5340 application core with nrfjprog ==")
    nrfjprog_program(nrfjprog, app_hex, network=False, verify=True, reset=True, chiperase=True, snr=snr)
    print("[OK] Application core programmed.")

    print("== Flashing nRF5340 network core with nrfjprog ==")
    nrfjprog_program(nrfjprog, net_hex, network=True, verify=True, reset=True, chiperase=True, snr=snr)
    print("[OK] Network core programmed.")


def flash_nrf_one_core(
    app_hex: Path | None = None,
    net_hex: Path | None = None,
    nrfjprog_opt: str | None = None,
    snr_opt: str | None = None,
):
    """Flash only one core; no recover and no chiperase."""
    if app_hex is None and net_hex is None:
        raise FileNotFoundError("Provide app_hex or net_hex.")
    if app_hex is not None and net_hex is not None:
        raise FileNotFoundError("Provide only one of app_hex or net_hex.")
    if app_hex is not None and not app_hex.exists():
        raise FileNotFoundError(f"App hex not found: {app_hex}")
    if net_hex is not None and not net_hex.exists():
        raise FileNotFoundError(f"Net hex not found: {net_hex}")

    nrfjprog = which_tool(
        "nrfjprog.exe",
        nrfjprog_opt,
        candidates=[
            # r"C:\Program Files\Nordic Semiconductor\nrf-command-line-tools\bin\nrfjprog.exe"
            "/usr/local/bin/nrfjprog",
        ],
    )

    snr = snr_opt or pick_last_jlink_snr(nrfjprog)
    print(f"[INFO] Using J-Link with serial number: {snr}")

    if app_hex is not None:
        print("== Flashing nRF5340 application core with nrfjprog ==")
        nrfjprog_program(
            nrfjprog,
            app_hex,
            network=False,
            verify=True,
            reset=True,
            chiperase=False,
            snr=snr,
        )
        print("[OK] Application core programmed.")
    else:
        print("== Flashing nRF5340 network core with nrfjprog ==")
        nrfjprog_program(
            nrfjprog,
            net_hex,
            network=True,
            verify=True,
            reset=True,
            chiperase=False,
            snr=snr,
        )
        print("[OK] Network core programmed.")
        # also need to reset the application core (without programming, just reset)
        nrfjprog_reset_core(nrfjprog, snr=snr, core="CP_APPLICATION")
        print("[OK] Application core reset.")


def nrfjprog_reset_core(nrfjprog, snr=None, core="CP_APPLICATION"):
    args = [nrfjprog, "-f", "NRF53"]
    if snr:
        args += ["-s", str(snr)]
    args += ["--reset", "--coprocessor", core]
    rc, out = run(args, timeout=120)
    if rc != 0 or "ERROR" in out.upper() or "failed" in out.lower():
        raise RuntimeError("nrfjprog reset failed; see log above.")


# ---------- CLI (click) ----------
@click.group(help="Flash helpers for APM32F103 (J-Link / DAPLink) and nRF5340.")
def cli():
    pass


@cli.command("jlink")
@click.option("--jlink", "jlink_bin", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to JLink OB bin (e.g. JLink-ob.bin).")
@click.option("--bl", "bl_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to STM32 bootloader hex (e.g. stm32f103xb_bl.hex).")
@click.option("--apm-device", default="APM32F103CB", show_default=True, help="J-Link device name for APM MCU.")
@click.option("--jlinktool", default=None, help="Path to JLinkExe if not on PATH.")
def cmd_jlink(jlink_bin, bl_hex, apm_device, jlinktool):
    """
    Flash STM32 bootloader, then J-Link OB image.

    Equivalent to:
    - flash STM32 BL (enables bootloader)
    - then flash J-Link OB which overwrites it
    """
    jlink_path = Path(jlink_bin).expanduser().resolve()
    bl_path = Path(bl_hex).expanduser().resolve()
    do_jlink(jlink_path, bl_path, apm_device, jlinktool)


@cli.command("daplink")
@click.option("--bl", "bl_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to STM32 bootloader hex (e.g. stm32f103xb_bl.hex).")
@click.option("--if", "if_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Optional path to DAPLink interface hex (e.g. stm32f103xb_if.hex).")
@click.option("--apm-device", default="APM32F103CB", show_default=True, help="J-Link device name for APM MCU.")
@click.option("--jlinktool", default=None, help="Path to JLinkExe if not on PATH.")
def cmd_daplink(bl_hex, if_hex, apm_device, jlinktool):
    """
    Flash the STM32 bootloader (DAPLink), optionally followed by the DAPLink interface.
    """
    bl_path = Path(bl_hex).expanduser().resolve()
    do_daplink(bl_path, apm_device, jlinktool)

    if_path = Path(if_hex).expanduser().resolve()
    # Small delay to let the target settle if needed
    time.sleep(1.0)
    do_daplink_if(if_path, apm_device)


@cli.command("nrf")
@click.option("--net", "net_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to nRF5340 network core hex.")
@click.option("--app", "app_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to nRF5340 application core hex.")
@click.option("--nrfjprog", default=None, help="Path to nrfjprog if not on PATH.")
@click.option("--snr", default=None, help="J-Link serial number to use (auto-detect if omitted).")
def cmd_nrf(net_hex, app_hex, nrfjprog, snr):
    """
    Flash both nRF5340 cores (application + network).
    """
    app_path = Path(app_hex).expanduser().resolve()
    net_path = Path(net_hex).expanduser().resolve()
    flash_nrf_both_cores(app_path, net_path, nrfjprog_opt=nrfjprog, snr_opt=snr)


@cli.command("jlink-nrf")
@click.option("--jlink", "jlink_bin", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to JLink OB bin (e.g. JLink-ob.bin).")
@click.option("--bl", "bl_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to STM32 bootloader hex (e.g. stm32f103xb_bl.hex).")
@click.option("--net", "net_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to nRF5340 network core hex.")
@click.option("--app", "app_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to nRF5340 application core hex.")
@click.option("--apm-device", default="APM32F103CB", show_default=True, help="J-Link device name for APM MCU.")
@click.option("--jlinktool", default=None, help="Path to JLinkExe if not on PATH.")
@click.option("--nrfjprog", default=None, help="Path to nrfjprog if not on PATH.")
@click.option("--snr", default=None, help="J-Link serial number to use (auto-detect if omitted).")
def cmd_jlink_nrf(jlink_bin, bl_hex, net_hex, app_hex, apm_device, jlinktool, nrfjprog, snr):
    """
    Flash J-Link OB (via STM32 bootloader), then flash both nRF5340 cores.
    """
    jlink_path = Path(jlink_bin).expanduser().resolve()
    bl_path = Path(bl_hex).expanduser().resolve()
    app_path = Path(app_hex).expanduser().resolve()
    net_path = Path(net_hex).expanduser().resolve()

    do_jlink(jlink_path, bl_path, apm_device, jlinktool)
    flash_nrf_both_cores(app_path, net_path, nrfjprog_opt=nrfjprog, snr_opt=snr)


@cli.command("daplink-nrf")
@click.option("--bl", "bl_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to STM32 bootloader hex (e.g. stm32f103xb_bl.hex).")
@click.option("--if", "if_hex", required=False, type=click.Path(exists=True, dir_okay=False), help="Optional path to DAPLink interface hex (e.g. stm32f103xb_if.hex).")
@click.option("--net", "net_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to nRF5340 network core hex.")
@click.option("--app", "app_hex", required=True, type=click.Path(exists=True, dir_okay=False), help="Path to nRF5340 application core hex.")
@click.option("--apm-device", default="APM32F103CB", show_default=True, help="J-Link device name for APM MCU.")
@click.option("--jlinktool", default=None, help="Path to JLinkExe if not on PATH.")
@click.option("--nrfjprog", default=None, help="Path to nrfjprog if not on PATH.")
@click.option("--snr", default=None, help="J-Link serial number to use (auto-detect if omitted).")
def cmd_daplink_nrf(bl_hex, if_hex, net_hex, app_hex, apm_device, jlinktool, nrfjprog, snr):
    """
    Flash STM32 bootloader (DAPLink), then flash both nRF5340 cores.
    """
    bl_path = Path(bl_hex).expanduser().resolve()
    if_path = Path(if_hex).expanduser().resolve()
    app_path = Path(app_hex).expanduser().resolve()
    net_path = Path(net_hex).expanduser().resolve()

    do_daplink(bl_path, apm_device, jlinktool)

    # Small delay to let the target settle if needed
    time.sleep(1.0)
    do_daplink_if(if_path, apm_device)

    flash_nrf_both_cores(app_path, net_path, nrfjprog_opt=nrfjprog, snr_opt=snr)


def main():
    cli(standalone_mode=True)


if __name__ == "__main__":
    sys.exit(main())
