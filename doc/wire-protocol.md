# The SwarmIT testbed wire protocol

This is the contract between the testbed firmware and any client that wants to
drive it. The Python control plane in `swarmit/testbed/protocol.py` is one
implementation of it, not the definition - anything here can be implemented
from scratch against this document.

The protocol is bespoke rather than CoAP or LwM2M, for reasons recorded in
"Why not CoAP" at the end. The price of that choice is that there is no
ecosystem to lean on: no schema registry, no conformance suite, no dissector
you get for free. This document and the Lua dissector beside it
(`doc/swarmit.lua`) are that price being paid.

## Framing

SwarmIT messages ride Mari as the payload of a data packet, tagged
`MARI_NEXT_PROTO_SWARMIT_TESTBED = 0x10`. Mari's header
(`mr_packet_header_t`) is:

| Field | Size | Notes |
|---|---|---|
| `version` | 1 | Mari protocol version |
| `type` | 1 | `mr_packet_type_t`; data packets are what carry SwarmIT |
| `network_id` | 2 | the swarm this frame belongs to |
| `dst` | 8 | device address, or `0xFFFFFFFFFFFFFFFF` for broadcast |
| `src` | 8 | device address |
| `next_proto` | 1 | `0x10` for everything in this document |

That is **21 bytes** of header out of `MARI_PACKET_MAX_SIZE` 255, leaving
**234 bytes** for a SwarmIT message.

Every SwarmIT message is one type byte followed by a body:

```
+------+--------------------------------+
| type |  body (0..233 bytes)           |
+------+--------------------------------+
```

**All multi-byte integers are little-endian.** Fixed-width strings are
NUL-padded and always NUL-terminated, so a 32-byte field holds at most 31
characters. A reader must treat trailing bytes it does not recognise as
padding and stop at the last field it knows, and must treat a body shorter
than expected as "that firmware predates this field" rather than as a
corrupt frame - see "Compatibility" below.

## Message types

`0x80`-`0x8F` is the core range; `0xA0`-`0xA3` were appended later for
custom messages and LH2 calibration (`0xA1` is reserved and never accepted). Direction is `H->D` for host to device
and `D->H` for device to host.

| ID | Name | Dir | Body | Purpose |
|---|---|---|---|---|
| `0x80` | `STATUS` | D->H | 35 B | periodic state, 1 Hz |
| `0x81` | `START` | H->D | 0 B | run the user image |
| `0x82` | `STOP` | H->D | 0 B | stop the user image |
| `0x83` | `RESET` | H->D | 8 B | set the reset position |
| `0x84` | `OTA_START` | H->D | 73 B | begin an image transfer |
| `0x85` | `OTA_CHUNK` | H->D | 141 B | one chunk of the image |
| `0x86` | `OTA_START_ACK` | D->H | 1 B | erase done, protocol version |
| `0x87` | `OTA_CHUNK_ACK` | - | - | **retired**, ID reserved |
| `0x88` | `EVENT_GPIO` | D->H | 7 B | a GPIO transition, timestamped |
| `0x89` | `EVENT_LOG` | D->H | 5..132 B | a log line or an LH2 sample |
| `0x8A` | `OTA_BLOCK_REPORT_REQ` | H->D | 5 B | which chunks of a block landed? |
| `0x8B` | `OTA_BLOCK_REPORT_RESP` | D->H | 9 B | the received-chunk bitmap |
| `0x8C` | `OTA_FINALIZE` | H->D | 32 B | verify the whole image |
| `0x8D` | `OTA_FINALIZE_RESP` | D->H | 1 B | did the image hash match? |
| `0x8E` | `REQUEST_MESSAGE` | H->D | 2 B | emit one message, once |
| `0x8F` | `DEVICE_INFO_RESP` | D->H | 154 B | what this device is running |
| `0xA0` | `MESSAGE` | H->D | 1..N B | opaque text to the user image |
| `0xA2` | `LH2_CAPTURE` | H->D | 0 B | capture one raw LH2 sample |
| `0xA3` | `LH2_CALIBRATION` | H->D | 84 B | one station's homography |

Mari's own metrics probes share the link but are **not** SwarmIT messages:
they are tagged `MARI_NEXT_PROTO_MARI_INTERNAL` and are claimed by payload
type, not by this range.

### `0x80` STATUS

Sent unprompted, once a second, by every device. This is the only periodic
message.

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `device` | 1 | 0 unknown, 1 DotBotV3, 2 DotBotV2, 3 nRF5340DK, 4 nRF52840DK |
| 1 | `status` | 1 | 0 Bootloader, 1 Running, 2 Stopping, 3 Resetting, 4 Programming |
| 2 | `battery` | 2 | mV |
| 4 | `pos_x` | 4 | mm; the device writes it unsigned |
| 8 | `pos_y` | 4 | mm; the device writes it unsigned |
| 12 | `reset_reason` | 4 | nRF5340 app-core `RESETREAS` as latched at boot |
| 16 | `fault` | 1 | 0 none, 1 hard fault, 2 secure fault |
| 17 | `from_ns` | 1 | 1 if the non-secure user image faulted |
| 18 | `cfsr` | 4 | Configurable Fault Status Register at fault |
| 22 | `sfsr` | 4 | Secure Fault Status Register at fault |
| 26 | `pc` | 4 | stacked PC at fault |
| 30 | `lr` | 4 | stacked LR at fault |
| 34 | `info_gen` | 1 | device-info generation counter, see `0x8F` |

Bytes 12..33 are the crash report. It is latched once at boot and never changes
during a run, so by the access-type rule below it is inventory and belongs in
`0x8F` - and it is most of this frame.

It stays here for one reason: a crash report is wanted precisely when a device
is unhealthy and barely reachable, and a 35-byte frame arriving every second
gets through where a 154-byte on-request reply does not. Airtime is not the
reason either way, since a Mari slot is sized for the maximum packet whatever
the payload holds, so moving it would be free. If that reachability argument
ever stops holding, nothing else keeps it here.

### `0x83` RESET

| Offset | Field | Size |
|---|---|---|
| 0 | `pos_x` | 4 |
| 4 | `pos_y` | 4 |

### `0x84` OTA_START

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `image_size` | 4 | bytes, padded to a 4-byte boundary by the host |
| 4 | `chunk_count` | 4 | |
| 8 | `version` | 1 | OTA protocol version; 2 = block/bitmap path |
| 9 | `image_name` | 32 | display-only label, NUL-padded |
| 41 | `image_version` | 32 | display-only label, NUL-padded |

The host pads the image so its length is a multiple of 4: the device writes
flash a 32-bit word at a time, so a final chunk whose length is not word-sized
would drop its tail bytes and fail the whole-image check. `0xFF` is the
erased-flash value, so the padding is a no-op on device.

`image_name` and `image_version` were appended after this message shipped, and
the device checks the received length before reading them. A controller that
sends only the first 9 bytes is understood as "no labels", and the device
reports the image by digest alone.

### `0x85` OTA_CHUNK

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `index` | 4 | chunk index |
| 4 | `chunk_size` | 1 | bytes valid in `chunk`; must be <= 128 |
| 5 | `sha` | 8 | first 8 bytes of SHA256 over `chunk[0..chunk_size)` |
| 13 | `chunk` | 128 | payload |

The device verifies `sha` before writing, and bounds `chunk_size` before any
copy - it comes off the radio and bounds two `memcpy` calls.

### `0x86` OTA_START_ACK

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `version` | 1 | OTA protocol version the device speaks |

A device predating the block path sends an **empty** body, which a host reads
as version 1. Version 2 means block/bitmap. A device that does not report 2
cannot be flashed over the air.

### `0x88` EVENT_GPIO

| Offset | Field | Size |
|---|---|---|
| 0 | `timestamp` | 4 |
| 4 | `port` | 1 |
| 5 | `pin` | 1 |
| 6 | `value` | 1 |

### `0x89` EVENT_LOG

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `timestamp` | 4 | device high-frequency timer, microseconds |
| 4 | `count` | 1 | bytes of `data` |
| 5 | `data` | `count` | usually UTF-8 text |

If `data[0]` is `0xCA` the payload is a raw LH2 capture rather than text, and
the rest is a sequence of `[lh_index:1][count1:4][count2:4]` samples. That tag
is what lets a host tell a calibration sample from a log line on one message
type.

### `0x8A` OTA_BLOCK_REPORT_REQ

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `block_index` | 4 | the block being asked about |
| 4 | `block_size` | 1 | chunks per block (32) |

Sent as a broadcast: every device answers in its own uplink cell, so one
request collects the whole fleet's progress in a single slotframe.

### `0x8B` OTA_BLOCK_REPORT_RESP

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `block_index` | 4 | the block the device currently holds |
| 4 | `received_mask` | 4 | bit *i* set: chunk `block_index * 32 + i` is in flash |
| 8 | `status` | 1 | reserved, 0 |

A device that has not started the requested block reports an **earlier**
`block_index`, which the host reads as "needs all of it".

### `0x8C` / `0x8D` OTA_FINALIZE

Request is the 32-byte expected SHA256 of the whole image. Response is one
byte, 1 if the device's own read-back of flash matched.

The device only records the image as its own once this check passes, so what
it reports can never describe an image that did not fully arrive.

### `0x8E` REQUEST_MESSAGE

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `msg_id` | 1 | which message to emit once; currently only `0x8F` |
| 1 | `flags` | 1 | reserved (response target); must be 0 |

Generic by construction. A future query adds a `msg_id` value rather than
another request/response pair - the mistake MAVLink made and then undid, when
`MAV_CMD_REQUEST_MESSAGE` superseded roughly fifteen bespoke
`MAV_CMD_REQUEST_*` commands.

A device must ignore a `msg_id` it does not implement rather than answering
with something else.

### `0x8F` DEVICE_INFO_RESP

The answer to "what is this device running?". Read once and cached by the
host; see "The generation counter" below for when to read it again.

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `info_version` | 1 | schema version of this message; currently 1 |
| 1 | `info_gen` | 1 | echoes the counter in `0x80` |
| 2 | `boot_count` | 4 | reboots since the record was created |
| 6 | `uptime_s` | 4 | seconds since this boot |
| 10 | `bl_version` | 32 | bootloader build stamp, `git describe --always --dirty` |
| 42 | `net_version` | 32 | network-core build stamp, same form |
| 74 | `image_state` | 1 | see below |
| 75 | `image_result` | 1 | see below |
| 76 | `image_size` | 4 | bytes, as flashed |
| 80 | `image_digest` | 8 | first 8 bytes of the image SHA256 |
| 88 | `image_name` | 32 | display-only, NUL-padded |
| 120 | `image_version` | 32 | display-only, NUL-padded |
| 152 | `lh2_homography_count` | 1 | 0 means uncalibrated |
| 153 | `lh2_flags` | 1 | bit 0 calibration valid, bit 1 loaded from flash |

Total 154 bytes, leaving 80 spare in a 234-byte payload.

**`image_digest` is the identity. `image_name` and `image_version` are
decoration.** A client compares digests; it must never make a decision on the
strings. This follows SUIT (RFC 9124 section 3.17), which states that text
"is for human consumption only" and "MUST NOT be the basis of any decision
made by the recipient", and MCUboot, which has no name field at all and whose
operator commands take an image hash. Two devices can carry the same label
over different bytes; only the digest distinguishes them. A device that
reports no name is not an error - a client shows the digest instead.

`bl_version` and `net_version` carry `-dirty` when built from a modified
tree. A dirty tree is a different artifact from the tagged commit even when
the tag matches, so a client must not treat `1.2.3-dirty` as `1.2.3`.

Field names are borrowed so that a gateway-side bridge to a standard is a
field mapping rather than a redesign:

| Ours | Standard |
|---|---|
| `image_state` | LwM2M Object 5 resource 3, *State* |
| `image_result` | LwM2M Object 5 resource 5, *Update Result* |
| `image_name` | LwM2M Object 5 resource 6, *PkgName* |
| `image_version` | LwM2M Object 5 resource 7, *PkgVersion* |
| `boot_count` | Matter *RebootCount*, 0x0033 attribute 0x0001 |
| `uptime_s` | Matter *UpTime*, 0x0033 attribute 0x0002 |
| 32-byte string cap | Matter, Zigbee and Thread identity strings all cap at 32 |

Two deviations from those definitions, both deliberate:

- `boot_count` is a `uint32` where Matter uses `uint16`. A testbed device
  reboots on every experiment start and stop, so 16 bits would wrap.
- `uptime_s` is a `uint32` where Matter uses `uint64` seconds. 32 bits is
  136 years and saves 4 bytes.

`image_state` (LwM2M *State*): 0 Idle, 1 Downloading, 2 Downloaded,
3 Updating.

`image_result` (LwM2M *Update Result*): 0 Initial, 1 Success, 2 Not enough
flash, 4 Connection lost, 5 Integrity check failure, 8 Firmware update
failed. Only these are produced.

There is deliberately **no boot-reason field**. Matter's *BootReasonEnum* is a
useful vocabulary, but everything needed to compute it - `reset_reason` and
`fault` - already rides `0x80`, so sending a device-side mapping as well would
put one fact on the wire twice and make correcting the mapping a firmware
flash. A client that wants the Matter value derives it: a latched fault or WDT0
is `HardwareWatchdogReset`, WDT1 or SREQ is `SoftwareReset`, zero or PIN is
`PowerOnReboot`, and anything else - a bare CPU lockup, which the enum has no
value for - is `Unspecified`. Order matters there: a cabled flash sets ctrl-ap,
SREQ and LOCKUP together, and reporting a freshly programmed device as
watchdog-reset says something went wrong when nothing did.

Deliberately **not** carried, so nobody adds them by reflex:

- **Network id.** A device only joins the network it was provisioned for, so
  the host knows it by construction. Reporting it would be the device telling
  us what we told it.
- **Link quality.** Mari already owns per-node PDR, RSSI at both ends and
  round-trip latency. Duplicating it would create two sources of truth.
- **A monotonic version integer.** Matter's `SoftwareVersion` works because it
  is an opaque monotonic `uint32`, but we have no build counter and make no
  on-device version-ordering decision: the machine-comparable field is the
  digest, and firmware comparison is string equality against the fleet
  majority. A monotonic integer would be unused state. This is the one place
  we knowingly diverge from Matter, Zigbee, Thread and OCF, which all expose
  every version twice.

### `0xA3` LH2_CALIBRATION

| Offset | Field | Size | Notes |
|---|---|---|---|
| 0 | `homography_count` | 4 | total matrices in this session |
| 4 | `homography_index` | 4 | 0-based |
| 8 | `homography` | 36 | 3x3 of little-endian `float32`, row-major, mapping the pinhole camera point to mm |
| 44 | `valid_mm` | 16 | `x_min, y_min, x_max, y_max` of plausible positions, `uint32` mm |
| 60 | `site_name` | 16 | NUL-padded |
| 76 | `calibration_id` | 8 | leading bytes of the calibration file's id |

The device accumulates matrices in RAM and commits to flash when
`homography_index == homography_count - 1`, then resets the SoC so both cores
come up with the new calibration.

## The generation counter

Device info is refreshed on change, never on a timer. `0x80` carries a
one-byte `info_gen`; a client caches the value that came with the `0x8F` it
last received and re-requests only when the two differ.

```
device                                  host
  |  STATUS(info_gen=7) ---------------> |  cached gen == 7, nothing to do
  |  STATUS(info_gen=7) ---------------> |  nothing to do
  |                                      |
  | (reboots, or an OTA finalizes)       |
  |  STATUS(info_gen=8) ---------------> |  8 != 7 -> stale
  | <----------- REQUEST_MESSAGE(0x8F)   |  one broadcast serves every stale device
  |  DEVICE_INFO_RESP(info_gen=8) -----> |  cache gen 8
```

Steady state costs **zero** device-info traffic. A flash campaign across the
whole fleet costs one broadcast, because devices answer in their own uplink
cells. Polling instead would not be free: at 100 nodes on a 265 ms slotframe,
a unicast poll every 10 s is about 12% of the downlink.

The counter changes on boot and on OTA finalize, including a *failed*
finalize - the result is something the host needs to see. It deliberately does
**not** change when a transfer starts, or every device in a flash campaign
would pull an info fetch into the middle of it.

**Ordering is load-bearing on both sides.** A device publishes every field
before moving the counter; a client samples the counter before reading the
fields. The two failure modes are not symmetric: that order means a racing
reader gets the *old* counter with new fields, caches the old value, and
corrects itself on the next status frame. The opposite order would pair a new
counter with stale fields, which a client would cache as current and never
correct.

`info_gen` is one byte on the wire and wraps at 256. Any difference means
"refetch", so a wrap back to the same cached value would need exactly 256
changes between two status frames one second apart. A config commit reboots the
device, so it moves the counter through the boot rather than as an event of its
own.

**Zero is reserved.** A device must never report `info_gen == 0`, and skips the
value on wrap. That makes zero mean exactly one thing to a client: this frame
was too short to carry the field and was zero-filled, i.e. the firmware predates
this message. A client uses that rather than a retry count to tell "cannot
answer" from "did not answer this time" - the first is a property of the device
and costs no requests at all, the second is worth asking again later.

The device keeps the counter in the same persistent record as everything else it
reports, and advances it once per boot and once per event. Deriving it from the
reboot count instead does not work: a boot that finalizes one image would end on
`boot_count + 1`, which is exactly where the next boot would start, so a client
sees no change across the reset and never refetches. Flashing a device and then
starting it is that sequence.

**On client restart, resync - never replay.** A fresh client has no cached
generation for any device, so the first status frame from each triggers exactly
one fetch. This is what every comparable system does: a gap means "cache
invalid, refetch", not "replay what I missed".

## Compatibility

The rule in both directions is **tolerate a short body, ignore a long one**.

Every field above was appended at some point, and devices and hosts are
upgraded separately, so version skew is the normal case rather than an error:

- A **host** reading a short `0x80` or `0x8F` zero-fills the missing tail. A
  35-byte status from firmware without the generation counter parses as
  generation 0; a 34-byte one from firmware without the crash report parses
  with a zeroed crash report.
- A **device** reading a short `0x84` checks the received length before
  touching `image_name`, because the bytes after the end of the frame are
  whatever the previous request left in the buffer. Reading them anyway is how
  a device ends up reporting a stale name with a confident-looking value.
- Neither side may fail a frame for having **extra** trailing bytes. That is
  what makes it possible to append a field at all.

A host should also expect a device never to answer `0x8E`: firmware predating
it drops unknown message types silently. Treat missing device info as unknown,
show it as unknown, and cap the retries - a device that ignores the request
several times is running old firmware, and asking forever puts a broadcast on
the downlink for the life of the session. Reset that verdict when the
device's generation counter moves, so a re-flashed device is probed afresh.

## Why not CoAP

Worth writing down, because "custom protocol where a standard would do" is a
real failure mode and the answer should be arguable rather than assumed. The
verdict is **align, do not adopt**: borrow the field vocabulary, skip the
transport.

- **CoAP (RFC 7252).** RFC 8323 is the IETF removing Version, Type and
  Message ID once the transport is reliable. Mari's TSCH ARQ and slot
  scheduler already provide what CON, message IDs and Block exist for, so
  adopting CoAP costs 8.5-25 kB of ROM to re-solve solved problems. CON's 2 s
  default ACK timeout is three orders of magnitude off a 1780 us slot.
- **OMA LwM2M.** Mandates CoAP plus DTLS-or-OSCORE plus Bootstrap plus
  Registration at 30-90 kB ROM, and Object 4 resource 4 is *mandatory* and is
  "IP Addresses", which is structurally unfillable on this link. We take its
  object vocabulary and none of its transport.
- **6TiSCH (RFC 9030 / 8180).** RFC 8180 makes RPL a MUST, so we would pay
  routing control traffic and per-node routing state to route toward the
  single gateway that is our only destination.

Two arguments specific to this system. First, Mari already made the
architectural call: `next_proto` reserves `0x10` for this protocol and `0xA1`
for IPv6, with a range reserved for standardized protocols, so an IP stack has
a designated home *alongside* the testbed protocol rather than instead of it.
Whatever a researcher wants on top - CoAP, LwM2M, DDS - they can deploy
themselves over `next_proto`.

Second, and independent of any code-size number: this protocol runs in the
bootloader and network core, outside the TrustZone sandbox, and its reason for
existing is that the testbed stays reachable when user firmware is buggy or
hostile. Adding 6LoWPAN, UDP and CoAP parsing to that path enlarges the attack
and failure surface of the one component that cannot be recovered over the air.

Precedent is on the bespoke side. Matter evaluated CoAP-over-6LoWPAN and built
its own binary TLV application layer instead; CoAP appears nowhere in its
stack. Thread uses CoAP as framing only, with its own URIs and TLVs, and never
adopted LwM2M. SmartMesh IP - the same TSCH lineage as Mari - exposes a
proprietary HDLC-framed binary command/response API, structurally identical to
`REQUEST_MESSAGE(msg_id) -> RESP`.

The documented regret about going bespoke is never the protocol; it is the
missing ecosystem. Hence this file and `doc/swarmit.lua`.
