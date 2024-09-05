#!/usr/bin/env python

import os
import logging
import time

from dataclasses import dataclass
from enum import Enum

import click
import serial
import structlog

from tqdm import tqdm
from cryptography.hazmat.primitives import hashes

from dotbot.hdlc import hdlc_encode, HDLCHandler, HDLCState
from dotbot.protocol import PROTOCOL_VERSION
from dotbot.serial_interface import SerialInterface, SerialInterfaceException


SERIAL_PORT = "/dev/ttyACM0"
BAUDRATE = 1000000
CHUNK_SIZE = 128
SWARMIT_PREAMBLE = bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07])


DEVICES_IDS = [
    0x24374c76b5cf8604
]


class NotificationType(Enum):
    """Types of notifications."""

    SWARMIT_NOTIFICATION_STATUS = 0
    SWARMIT_NOTIFICATION_OTA_START_ACK = 1
    SWARMIT_NOTIFICATION_OTA_CHUNK_ACK = 2
    SWARMIT_NOTIFICATION_EVENT_GPIO = 3
    SWARMIT_NOTIFICATION_EVENT_LOG = 4

class RequestType(Enum):
    """Types of requests."""

    SWARMIT_REQ_EXPERIMENT_START = 1
    SWARMIT_REQ_EXPERIMENT_STOP = 2
    SWARMIT_REQ_OTA_START = 3
    SWARMIT_REQ_OTA_CHUNK = 4


@dataclass
class DataChunk:
    """Class that holds data chunks."""

    index: int
    size: int
    data: bytes


class SwarmitStartExperiment:
    """Class used to start an experiment."""

    def __init__(self, port, baudrate, firmware):
        self.serial = SerialInterface(port, baudrate, self.on_byte_received)
        self.hdlc_handler = HDLCHandler()
        self.start_ack_received = False
        self.firmware = firmware
        self.last_acked_index = -1
        self.last_deviceid_ack = None
        self.chunks = []
        self.fw_hash = None
        self.device_id = None
        # Just write a single byte to fake a DotBot gateway handshake
        self.serial.write(int(PROTOCOL_VERSION).to_bytes(length=1))

    def on_byte_received(self, byte):
        self.hdlc_handler.handle_byte(byte)
        if self.hdlc_handler.state == HDLCState.READY:
            payload = self.hdlc_handler.payload
            if not payload:
                return
            self.last_deviceid_ack = int.from_bytes(payload[0:8], byteorder="little")
            if payload[8] == NotificationType.SWARMIT_NOTIFICATION_OTA_START_ACK.value:
                self.start_ack_received = True
            elif payload[8] == NotificationType.SWARMIT_NOTIFICATION_OTA_CHUNK_ACK.value:
                self.last_acked_index = int.from_bytes(payload[9:14], byteorder="little")

    def init(self):
        digest = hashes.Hash(hashes.SHA256())
        chunks_count = int(len(self.firmware) / CHUNK_SIZE) + int(len(self.firmware) % CHUNK_SIZE != 0)
        for chunk_idx in range(chunks_count):
            if chunk_idx == chunks_count - 1:
                chunk_size = len(self.firmware) % CHUNK_SIZE
            else:
                chunk_size = CHUNK_SIZE
            data = self.firmware[chunk_idx * CHUNK_SIZE : chunk_idx * CHUNK_SIZE + chunk_size]
            digest.update(data)
            self.chunks.append(
                DataChunk(
                    index=chunk_idx,
                    size=chunk_size,
                    data=data,
                )
            )
        print(f"Radio chunks ({CHUNK_SIZE}B): {len(self.chunks)}")
        self.fw_hash = digest.finalize()

    def start_ota(self, device_id):
        self.device_id = device_id
        buffer = bytearray()
        buffer += SWARMIT_PREAMBLE
        buffer += int(RequestType.SWARMIT_REQ_OTA_START.value).to_bytes(
            length=1, byteorder="little"
        )
        buffer += len(self.firmware).to_bytes(length=4, byteorder="little")
        buffer += self.fw_hash
        print("Sending start ota notification...")
        self.serial.write(hdlc_encode(buffer))
        timeout = 0  # ms
        while self.start_ack_received is False and timeout < 10000:
            timeout += 1
            time.sleep(0.0001)
        return self.start_ack_received is True and self.last_deviceid_ack == self.device_id

    def send_chunk(self, chunk):
        send_time = time.time()
        send = True
        tries = 0
        while tries < 3:
            if self.last_acked_index == chunk.index:
                break
            if send is True:
                buffer = bytearray()
                buffer += SWARMIT_PREAMBLE
                buffer += int(RequestType.SWARMIT_REQ_OTA_CHUNK.value).to_bytes(
                    length=1, byteorder="little"
                )
                buffer += int(chunk.index).to_bytes(length=4, byteorder="little")
                buffer += int(chunk.size).to_bytes(length=1, byteorder="little")
                buffer += chunk.data
                self.serial.write(hdlc_encode(buffer))
                send_time = time.time()
                tries += 1
            time.sleep(0.001)
            send = time.time() - send_time > 0.1
        else:
            raise Exception(f"chunk #{chunk.index} not acknowledged. Aborting.")
        self.last_acked_index = -1
        self.last_deviceid_ack = None

    def transfer(self):
        if self.device_id is None:
            raise Exception("Device ID not set.")
        data_size = len(self.firmware)
        progress = tqdm(range(0, data_size), unit="B", unit_scale=False, colour="green", ncols=100)
        progress.set_description(f"Loading firmware ({int(data_size / 1024)}kB)")
        for chunk in self.chunks:
            self.send_chunk(chunk)
            progress.update(chunk.size)
        progress.close()

    def start(self):
        buffer = bytearray()
        buffer += SWARMIT_PREAMBLE
        buffer += int(RequestType.SWARMIT_REQ_EXPERIMENT_START.value).to_bytes(
            length=1, byteorder="little"
        )
        buffer += len(self.firmware).to_bytes(length=4, byteorder="little")
        buffer += self.fw_hash
        self.serial.write(hdlc_encode(buffer))
        timeout = 0  # ms
        while self.start_ack_received is False and timeout < 10000:
            timeout += 1
            time.sleep(0.01)
        return self.start_ack_received is True


class SwarmitStopExperiment:
    """Class used to stop an experiment."""

    def __init__(self, port, baudrate):
        self.serial = SerialInterface(port, baudrate, lambda x: None)
        self.hdlc_handler = HDLCHandler()
        # Just write a single byte to fake a DotBot gateway handshake
        self.serial.write(int(PROTOCOL_VERSION).to_bytes(length=1))

    def stop(self):
        buffer = bytearray()
        buffer += SWARMIT_PREAMBLE
        buffer += int(RequestType.SWARMIT_REQ_EXPERIMENT_STOP.value).to_bytes(
            length=1, byteorder="little"
        )
        self.serial.write(hdlc_encode(buffer))


@click.group()
@click.option(
    "-p",
    "--port",
    default=SERIAL_PORT,
    help=f"Serial port to use to send the bitstream to the gateway. Default: {SERIAL_PORT}.",
)
@click.option(
    "-b",
    "--baudrate",
    default=BAUDRATE,
    help=f"Serial port baudrate. Default: {BAUDRATE}.",
)
@click.pass_context
def main(ctx, port, baudrate):
    # Disable logging configure in PyDotBot
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL),
    )
    ctx.ensure_object(dict)
    ctx.obj['port'] = port
    ctx.obj['baudrate'] = baudrate


@main.command()
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Start the experiment without prompt.",
)
@click.argument("firmware", type=click.File(mode="rb", lazy=True))
@click.pass_context
def start(ctx, yes, firmware):
    try:
        experiment = SwarmitStartExperiment(
            ctx.obj['port'],
            ctx.obj['baudrate'],
            bytearray(firmware.read()),
        )
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        print(f"Error: {exc}")
        return
    print(f"Image size: {len(experiment.firmware)}B")
    print("")
    if yes is False:
        click.confirm("Do you want to continue?", default=True, abort=True)
    ret = experiment.init()
    for device_id in DEVICES_IDS:
        print(f"Preparing device {hex(device_id)}")
        ret = experiment.start_ota(device_id)
        if ret is False:
            print(f"Error: No start acknowledgment received from {hex(device_id)}. Aborting.")
            return
        try:
            experiment.transfer()
        except Exception as exc:
            print(f"Error during transfering image to {hex(device_id)}: {exc}")
            return
    experiment.start()
    print("Experiment started.")


@main.command()
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Force experiment stop.",
)
@click.pass_context
def stop(ctx, yes):
    try:
        experiment = SwarmitStopExperiment(
            ctx.obj['port'],
            ctx.obj['baudrate'],
        )
    except (
        SerialInterfaceException,
        serial.serialutil.SerialException,
    ) as exc:
        print(f"Error: {exc}")
        return
    experiment.stop()

if __name__ == '__main__':
    main(obj={})