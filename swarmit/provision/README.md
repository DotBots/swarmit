# Swarmit Provisioning (Skeleton)

This directory contains a Click-based CLI skeleton for provisioning DotBot devices and gateways.

## Commands

### Fetch firmware assets

Download firmware into `bin/<fw-version>/`:

```bash
swarmit-provision fetch --fw-version v0.6.0
```

Use local artifacts (e.g. for dev builds):

```bash
swarmit-provision fetch --fw-version local --local-root /path/to/swarmit
```

### Provision devices

Flash app + net cores and write config:

```bash
swarmit-provision flash --device dotbot-v3 --fw-version v0.6.0 --network-id 0100
```

Use a TOML config:

```toml
[provisioning]
network_id = "0100"
firmware_version = "v0.6.0"
```

```bash
swarmit-provision flash --device dotbot-v3 --config provision-config-sample.toml --fw-version v0.6.1
```

### Flash explicit hex files

```bash
swarmit-provision flash-hex --app path/to/app.hex --net path/to/net.hex
```

### Programmer bring-up (J-Link OB / DAPLink)

```bash
swarmit-provision flash-bringup --programmer jlink --files-dir ../dotbot-programmer-fw/
swarmit-provision flash-bringup --programmer daplink --files-dir ../dotbot-programmer-fw/
```

## Notes

- This is a skeleton. Each command prints TODOs and validates inputs.
- `flash` will later create a temporary config hex (e.g. `/tmp/config-dotbot-v3-v0.6.0-0100.hex`) and use `nrfutil` to program it.
- `tomllib` is used for parsing TOML (Python 3.11+). If you are on an older Python, install `tomli`.
