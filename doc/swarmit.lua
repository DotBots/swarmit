--
-- Wireshark dissector for the SwarmIT testbed protocol.
--
-- The protocol is bespoke rather than CoAP, so nothing decodes it for free.
-- This file is the other half of that trade (see doc/wire-protocol.md): it
-- makes a capture readable without anyone having to hold the byte offsets in
-- their head.
--
-- Install:
--     cp doc/swarmit.lua ~/.local/lib/wireshark/plugins/     # Linux
--     cp doc/swarmit.lua ~/.config/wireshark/plugins/        # also works
--     cp doc/swarmit.lua "$HOME/.wireshark/plugins/"         # macOS, older
-- then Analyze > Reload Lua Plugins (or restart Wireshark).
--
-- Use: on a capture of Mari frames, "Decode As" the payload as SWARMIT, or
-- let the mari dissector hand off on next_proto == 0x10 if it is installed.
-- To read a bare SwarmIT message (one type byte + body, e.g. pasted from the
-- "Raw status pkt" field that `swarm info` prints), use
-- `swarmit_message.type` as the Decode As entry point.
--
-- Everything here is little-endian, matching the wire format.
--

local swarmit = Proto("swarmit", "SwarmIT testbed protocol")

local MSG = {
    [0x80] = "STATUS",
    [0x81] = "START",
    [0x82] = "STOP",
    [0x83] = "RESET",
    [0x84] = "OTA_START",
    [0x85] = "OTA_CHUNK",
    [0x86] = "OTA_START_ACK",
    [0x87] = "OTA_CHUNK_ACK (retired)",
    [0x88] = "EVENT_GPIO",
    [0x89] = "EVENT_LOG",
    [0x8A] = "OTA_BLOCK_REPORT_REQ",
    [0x8B] = "OTA_BLOCK_REPORT_RESP",
    [0x8C] = "OTA_FINALIZE",
    [0x8D] = "OTA_FINALIZE_RESP",
    [0x8E] = "REQUEST_MESSAGE",
    [0x8F] = "DEVICE_INFO_RESP",
    [0xA0] = "MESSAGE",
    [0xA2] = "LH2_CAPTURE",
    [0xA3] = "LH2_CALIBRATION",
}

local DEVICE_TYPE = {
    [0] = "Unknown",
    [1] = "DotBotV3",
    [2] = "DotBotV2",
    [3] = "nRF5340DK",
    [4] = "nRF52840DK",
}

local STATUS_TYPE = {
    [0] = "Bootloader",
    [1] = "Running",
    [2] = "Stopping",
    [3] = "Resetting",
    [4] = "Programming",
}

local FAULT_TYPE = {
    [0] = "NoFault",
    [1] = "HardFault",
    [2] = "SecureFault",
}

-- LwM2M Object 5 resource 3 (State).
local IMAGE_STATE = {
    [0] = "Idle",
    [1] = "Downloading",
    [2] = "Downloaded",
    [3] = "Updating",
}

-- LwM2M Object 5 resource 5 (Update Result). Only the values the firmware
-- can produce are named; anything else shows as its number.
local IMAGE_RESULT = {
    [0] = "Initial",
    [1] = "Success",
    [2] = "NotEnoughFlash",
    [4] = "ConnectionLost",
    [5] = "IntegrityCheckFailure",
    [8] = "UpdateFailed",
}

local INFO_STRING_LEN = 32
local IMAGE_DIGEST_LEN = 8
local LH2_SITE_NAME_LEN = 16
local LH2_CALIBRATION_ID_LEN = 8
local OTA_CHUNK_SIZE = 128
local SHA256_LEN = 32
-- Body lengths of STATUS as it grew: fields were appended, so a short frame
-- means older firmware rather than a malformed packet.
local STATUS_LEGACY_LEN = 12
local STATUS_WITH_CRASH_LEN = 34
local STATUS_FULL_LEN = 35

local f = swarmit.fields

f.type = ProtoField.uint8("swarmit.type", "Message type", base.HEX, MSG)

-- STATUS
f.device = ProtoField.uint8("swarmit.device", "Device type", base.DEC, DEVICE_TYPE)
f.status = ProtoField.uint8("swarmit.status", "Status", base.DEC, STATUS_TYPE)
f.battery = ProtoField.uint16("swarmit.battery", "Battery", base.DEC, nil, nil, "mV")
f.pos_x = ProtoField.int32("swarmit.pos_x", "Position X", base.DEC, nil, nil, "mm")
f.pos_y = ProtoField.int32("swarmit.pos_y", "Position Y", base.DEC, nil, nil, "mm")
f.reset_reason = ProtoField.uint32("swarmit.reset_reason", "Reset reason (RESETREAS)", base.HEX)
f.fault = ProtoField.uint8("swarmit.fault", "Latched fault", base.DEC, FAULT_TYPE)
f.from_ns = ProtoField.uint8("swarmit.from_ns", "Faulted in non-secure", base.DEC)
f.cfsr = ProtoField.uint32("swarmit.cfsr", "CFSR", base.HEX)
f.sfsr = ProtoField.uint32("swarmit.sfsr", "SFSR", base.HEX)
f.pc = ProtoField.uint32("swarmit.pc", "PC at fault", base.HEX)
f.lr = ProtoField.uint32("swarmit.lr", "LR at fault", base.HEX)
f.info_gen = ProtoField.uint8("swarmit.info_gen", "Device-info generation", base.DEC)

-- OTA
f.image_size = ProtoField.uint32("swarmit.image_size", "Image size", base.DEC, nil, nil, "bytes")
f.chunk_count = ProtoField.uint32("swarmit.chunk_count", "Chunk count", base.DEC)
f.ota_version = ProtoField.uint8("swarmit.ota_version", "OTA protocol version", base.DEC)
f.chunk_index = ProtoField.uint32("swarmit.chunk_index", "Chunk index", base.DEC)
f.chunk_size = ProtoField.uint8("swarmit.chunk_size", "Chunk size", base.DEC, nil, nil, "bytes")
f.chunk_sha = ProtoField.bytes("swarmit.chunk_sha", "Chunk SHA256 (first 8)")
f.chunk = ProtoField.bytes("swarmit.chunk", "Chunk data")
f.block_index = ProtoField.uint32("swarmit.block_index", "Block index", base.DEC)
f.block_size = ProtoField.uint8("swarmit.block_size", "Chunks per block", base.DEC)
f.received_mask = ProtoField.uint32("swarmit.received_mask", "Received chunk bitmap", base.HEX)
f.report_status = ProtoField.uint8("swarmit.report_status", "Status (reserved)", base.DEC)
f.finalize_sha = ProtoField.bytes("swarmit.finalize_sha", "Expected whole-image SHA256")
f.finalize_ok = ProtoField.uint8("swarmit.finalize_ok", "Image SHA256 matched", base.DEC)

-- REQUEST_MESSAGE
f.msg_id = ProtoField.uint8("swarmit.msg_id", "Requested message", base.HEX, MSG)
f.req_flags = ProtoField.uint8("swarmit.req_flags", "Flags (reserved)", base.HEX)

-- DEVICE_INFO_RESP
f.info_version = ProtoField.uint8("swarmit.info_version", "Info schema version", base.DEC)
f.boot_count = ProtoField.uint32("swarmit.boot_count", "Boot count", base.DEC)
f.uptime_s = ProtoField.uint32("swarmit.uptime_s", "Uptime", base.DEC, nil, nil, "s")
f.bl_version = ProtoField.stringz("swarmit.bl_version", "Bootloader version")
f.net_version = ProtoField.stringz("swarmit.net_version", "Network core version")
f.image_state = ProtoField.uint8("swarmit.image_state", "Image state", base.DEC, IMAGE_STATE)
f.image_result = ProtoField.uint8("swarmit.image_result", "Image result", base.DEC, IMAGE_RESULT)
f.image_digest = ProtoField.bytes("swarmit.image_digest", "Image digest (first 8 of SHA256)")
f.image_name = ProtoField.stringz("swarmit.image_name", "Image name")
f.image_version = ProtoField.stringz("swarmit.image_version", "Image version")
f.lh2_station_mask = ProtoField.uint16("swarmit.lh2_station_mask", "LH2 station mask", base.HEX)
f.lh2_flags = ProtoField.uint8("swarmit.lh2_flags", "LH2 flags", base.HEX)
f.lh2_valid = ProtoField.bool("swarmit.lh2_valid", "Calibration valid", 8, nil, 0x01)
f.lh2_from_flash = ProtoField.bool("swarmit.lh2_from_flash", "Loaded from flash", 8, nil, 0x02)
f.lh2_site_name = ProtoField.stringz("swarmit.lh2_site_name", "LH2 site name")
f.lh2_calibration_id = ProtoField.bytes("swarmit.lh2_calibration_id", "LH2 calibration id")

-- Events
f.timestamp = ProtoField.uint32("swarmit.timestamp", "Timestamp", base.DEC, nil, nil, "us")
f.count = ProtoField.uint8("swarmit.count", "Data length", base.DEC, nil, nil, "bytes")
f.data = ProtoField.bytes("swarmit.data", "Data")
f.text = ProtoField.string("swarmit.text", "Text")
f.gpio_port = ProtoField.uint8("swarmit.gpio_port", "GPIO port", base.DEC)
f.gpio_pin = ProtoField.uint8("swarmit.gpio_pin", "GPIO pin", base.DEC)
f.gpio_value = ProtoField.uint8("swarmit.gpio_value", "GPIO value", base.DEC)

-- LH2 calibration
f.station_mask = ProtoField.uint32("swarmit.station_mask", "Station mask", base.HEX)
f.station_index = ProtoField.uint32("swarmit.station_index", "Station index", base.DEC)
f.homography = ProtoField.bytes("swarmit.homography", "Homography matrix (3x3 float32)")
f.valid_mm = ProtoField.bytes("swarmit.valid_mm", "Station rectangle (4x uint32, mm)")
f.site_name = ProtoField.stringz("swarmit.site_name", "Site name")
f.calibration_id = ProtoField.bytes("swarmit.calibration_id", "Calibration id")

-- LH2 raw-capture samples ride inside EVENT_LOG behind this tag byte.
local LH2_CALIB_TAG = 0xCA
f.lh2_sample_index = ProtoField.uint8("swarmit.lh2_sample_index", "Basestation index", base.DEC)
f.lh2_count1 = ProtoField.uint32("swarmit.lh2_count1", "Count 1", base.DEC)
f.lh2_count2 = ProtoField.uint32("swarmit.lh2_count2", "Count 2", base.DEC)

local ef_short = ProtoExpert.new("swarmit.short", "Body shorter than this message defines",
                                 expert.group.MALFORMED, expert.severity.NOTE)
local ef_trailing = ProtoExpert.new("swarmit.trailing", "Trailing bytes after the known fields",
                                    expert.group.UNDECODED, expert.severity.CHAT)
local ef_unknown = ProtoExpert.new("swarmit.unknown_type", "Unknown SwarmIT message type",
                                   expert.group.UNDECODED, expert.severity.WARN)

swarmit.experts = { ef_short, ef_trailing, ef_unknown }

--- Read a NUL-padded fixed-width string, the way the firmware writes it.
local function add_string_field(tree, field, buf, offset, len)
    tree:add(field, buf(offset, len))
    return offset + len
end

--- STATUS grew twice by appending, so decode as much as the body carries and
--- say which vintage it is rather than flagging an error.
local function dissect_status(buf, tree, len)
    local o = 0
    tree:add_le(f.device, buf(o, 1)); o = o + 1
    tree:add_le(f.status, buf(o, 1)); o = o + 1
    tree:add_le(f.battery, buf(o, 2)); o = o + 2
    tree:add_le(f.pos_x, buf(o, 4)); o = o + 4
    tree:add_le(f.pos_y, buf(o, 4)); o = o + 4

    if len < STATUS_WITH_CRASH_LEN then
        tree:append_text(" [legacy: no crash report]")
        return o
    end

    local crash = tree:add(swarmit, buf(o, 22), "Crash report")
    crash:add_le(f.reset_reason, buf(o, 4)); o = o + 4
    crash:add_le(f.fault, buf(o, 1)); o = o + 1
    crash:add_le(f.from_ns, buf(o, 1)); o = o + 1
    crash:add_le(f.cfsr, buf(o, 4)); o = o + 4
    crash:add_le(f.sfsr, buf(o, 4)); o = o + 4
    crash:add_le(f.pc, buf(o, 4)); o = o + 4
    crash:add_le(f.lr, buf(o, 4)); o = o + 4

    if len < STATUS_FULL_LEN then
        tree:append_text(" [no generation counter]")
        return o
    end

    tree:add_le(f.info_gen, buf(o, 1)); o = o + 1
    return o
end

--- Decode as many whole fields as the body actually carries.
---
--- Every field here sits at a fixed offset, so a short body decodes cleanly up
--- to wherever it ends. Bailing out instead would contradict the rule the
--- schema states for every message - tolerate a short body, it means older
--- firmware - and would show nothing at all for a frame that is mostly
--- readable.
local function dissect_device_info(buf, tree, len)
    local o = 0
    local function room(n) return o + n <= len end

    if not room(1) then return o end
    tree:add_le(f.info_version, buf(o, 1)); o = o + 1
    if not room(1) then return o end
    tree:add_le(f.info_gen, buf(o, 1)); o = o + 1
    if not room(4) then return o end
    tree:add_le(f.boot_count, buf(o, 4)); o = o + 4
    if not room(4) then return o end
    tree:add_le(f.uptime_s, buf(o, 4)); o = o + 4
    if not room(INFO_STRING_LEN) then return o end
    o = add_string_field(tree, f.bl_version, buf, o, INFO_STRING_LEN)
    if not room(INFO_STRING_LEN) then return o end
    o = add_string_field(tree, f.net_version, buf, o, INFO_STRING_LEN)
    if not room(1) then return o end
    tree:add_le(f.image_state, buf(o, 1)); o = o + 1
    if not room(1) then return o end
    tree:add_le(f.image_result, buf(o, 1)); o = o + 1
    if not room(4) then return o end
    tree:add_le(f.image_size, buf(o, 4)); o = o + 4
    if not room(IMAGE_DIGEST_LEN) then return o end
    tree:add(f.image_digest, buf(o, IMAGE_DIGEST_LEN)); o = o + IMAGE_DIGEST_LEN
    if not room(INFO_STRING_LEN) then return o end
    o = add_string_field(tree, f.image_name, buf, o, INFO_STRING_LEN)
    if not room(INFO_STRING_LEN) then return o end
    o = add_string_field(tree, f.image_version, buf, o, INFO_STRING_LEN)
    if not room(2) then return o end
    tree:add_le(f.lh2_station_mask, buf(o, 2)); o = o + 2
    if not room(1) then return o end
    local flags = tree:add_le(f.lh2_flags, buf(o, 1))
    flags:add_le(f.lh2_valid, buf(o, 1))
    flags:add_le(f.lh2_from_flash, buf(o, 1))
    o = o + 1
    if not room(LH2_SITE_NAME_LEN) then return o end
    o = add_string_field(tree, f.lh2_site_name, buf, o, LH2_SITE_NAME_LEN)
    if not room(LH2_CALIBRATION_ID_LEN) then return o end
    tree:add(f.lh2_calibration_id, buf(o, LH2_CALIBRATION_ID_LEN)); o = o + LH2_CALIBRATION_ID_LEN
    return o
end

--- EVENT_LOG carries either text or, behind a tag byte, raw LH2 samples.
local function dissect_event_log(buf, tree, len)
    local o = 0
    tree:add_le(f.timestamp, buf(o, 4)); o = o + 4
    local count = buf(o, 1):le_uint()
    tree:add_le(f.count, buf(o, 1)); o = o + 1
    if count == 0 or o + count > len then
        return o
    end

    local body = buf(o, count)
    if body(0, 1):uint() == LH2_CALIB_TAG then
        local samples = tree:add(swarmit, body, "LH2 raw capture")
        local so = 1
        while so + 9 <= count do
            local s = samples:add(swarmit, body(so, 9), "Sample")
            s:add_le(f.lh2_sample_index, body(so, 1))
            s:add_le(f.lh2_count1, body(so + 1, 4))
            s:add_le(f.lh2_count2, body(so + 5, 4))
            so = so + 9
        end
    else
        tree:add(f.text, body)
    end
    return o + count
end

--- Dissect one SwarmIT message: a type byte plus a body.
--- Returns the number of bytes consumed, or 0 if the type is not ours.
local function dissect_message(buf, pinfo, root)
    local len = buf:len()
    if len < 1 then
        return 0
    end

    local msg_type = buf(0, 1):uint()
    local name = MSG[msg_type]
    if name == nil then
        return 0
    end

    pinfo.cols.protocol = "SwarmIT"
    pinfo.cols.info = name

    local tree = root:add(swarmit, buf(), "SwarmIT " .. name)
    tree:add(f.type, buf(0, 1))

    local body = buf(1)
    local body_len = len - 1
    local consumed = 0

    if msg_type == 0x80 then
        if body_len < STATUS_LEGACY_LEN then
            tree:add_proto_expert_info(ef_short)
            return len
        end
        consumed = dissect_status(body, tree, body_len)
    elseif msg_type == 0x83 and body_len >= 8 then
        tree:add_le(f.pos_x, body(0, 4))
        tree:add_le(f.pos_y, body(4, 4))
        consumed = 8
    elseif msg_type == 0x84 and body_len >= 9 then
        tree:add_le(f.image_size, body(0, 4))
        tree:add_le(f.chunk_count, body(4, 4))
        tree:add_le(f.ota_version, body(8, 1))
        consumed = 9
        -- Appended after this message shipped; a shorter frame means the
        -- controller did not send labels, which is legal.
        if body_len >= 9 + 2 * INFO_STRING_LEN then
            add_string_field(tree, f.image_name, body, 9, INFO_STRING_LEN)
            add_string_field(tree, f.image_version, body, 9 + INFO_STRING_LEN, INFO_STRING_LEN)
            consumed = 9 + 2 * INFO_STRING_LEN
        else
            tree:append_text(" [no image labels]")
        end
    elseif msg_type == 0x85 and body_len >= 13 then
        tree:add_le(f.chunk_index, body(0, 4))
        local size = body(4, 1):le_uint()
        tree:add_le(f.chunk_size, body(4, 1))
        tree:add(f.chunk_sha, body(5, 8))
        local avail = math.min(size, body_len - 13)
        if avail > 0 then
            tree:add(f.chunk, body(13, avail))
        end
        -- The chunk field is fixed-width on the wire even when only
        -- chunk_size bytes are meaningful.
        consumed = 13 + math.min(OTA_CHUNK_SIZE, body_len - 13)
    elseif msg_type == 0x86 then
        if body_len >= 1 then
            tree:add_le(f.ota_version, body(0, 1))
            consumed = 1
        else
            -- An empty ack is how a pre-block bootloader answers, and it
            -- means version 1.
            tree:append_text(" [empty: legacy bootloader, version 1]")
        end
    elseif msg_type == 0x88 and body_len >= 7 then
        tree:add_le(f.timestamp, body(0, 4))
        tree:add_le(f.gpio_port, body(4, 1))
        tree:add_le(f.gpio_pin, body(5, 1))
        tree:add_le(f.gpio_value, body(6, 1))
        consumed = 7
    elseif msg_type == 0x89 and body_len >= 5 then
        consumed = dissect_event_log(body, tree, body_len)
    elseif msg_type == 0x8A and body_len >= 5 then
        tree:add_le(f.block_index, body(0, 4))
        tree:add_le(f.block_size, body(4, 1))
        consumed = 5
    elseif msg_type == 0x8B and body_len >= 9 then
        tree:add_le(f.block_index, body(0, 4))
        tree:add_le(f.received_mask, body(4, 4))
        tree:add_le(f.report_status, body(8, 1))
        consumed = 9
    elseif msg_type == 0x8C and body_len >= SHA256_LEN then
        tree:add(f.finalize_sha, body(0, SHA256_LEN))
        consumed = SHA256_LEN
    elseif msg_type == 0x8D and body_len >= 1 then
        tree:add_le(f.finalize_ok, body(0, 1))
        consumed = 1
    elseif msg_type == 0x8E and body_len >= 2 then
        tree:add(f.msg_id, body(0, 1))
        tree:add(f.req_flags, body(1, 1))
        pinfo.cols.info = name .. " -> " .. (MSG[body(0, 1):uint()] or "?")
        consumed = 2
    elseif msg_type == 0x8F then
        consumed = dissect_device_info(body, tree, body_len)
        if body_len < 179 then
            tree:append_text(" [truncated: older schema or a short frame]")
            tree:add_proto_expert_info(ef_short)
            return len
        end
    elseif msg_type == 0xA0 and body_len >= 1 then
        local count = body(0, 1):le_uint()
        tree:add_le(f.count, body(0, 1))
        if count > 0 and 1 + count <= body_len then
            tree:add(f.text, body(1, count))
        end
        consumed = 1 + math.min(count, body_len - 1)
    elseif msg_type == 0xA3 and body_len >= 84 then
        tree:add_le(f.station_mask, body(0, 4))
        tree:add_le(f.station_index, body(4, 4))
        tree:add(f.homography, body(8, 36))
        tree:add(f.valid_mm, body(44, 16))
        tree:add(f.site_name, body(60, 16))
        tree:add(f.calibration_id, body(76, 8))
        consumed = 84
    else
        -- START / STOP / LH2_CAPTURE have no body, and a retired or truncated
        -- message falls through here.
        consumed = 0
    end

    if consumed > 0 and consumed < body_len then
        tree:add_proto_expert_info(ef_trailing)
    end
    return len
end

function swarmit.dissector(buf, pinfo, root)
    local consumed = dissect_message(buf, pinfo, root)
    if consumed == 0 and buf:len() >= 1 then
        local tree = root:add(swarmit, buf(), "SwarmIT (unrecognized)")
        tree:add(f.type, buf(0, 1))
        tree:add_proto_expert_info(ef_unknown)
        return buf:len()
    end
    return consumed
end

-- Hand-off from a mari dissector, if one is installed: next_proto 0x10 is
-- this protocol. Registering the table entry is harmless when it is not.
local ok, mari_table = pcall(DissectorTable.get, "mari.next_proto")
if ok and mari_table then
    mari_table:add(0x10, swarmit)
end

-- Also decode a bare message (one type byte + body) carried in a DLT_USER0
-- capture, so a payload pasted out of the "Raw status pkt" line that
-- `swarm info` prints can be read without a full Mari capture:
--
--     text2pcap -l 147 -t "%H:%M:%S." hex.txt out.pcap
--     tshark -r out.pcap -V
--
-- 147 is DLT_USER0. This is the standard way to hand Wireshark a naked
-- protocol payload.
DissectorTable.get("wtap_encap"):add(wtap.USER0, swarmit)
