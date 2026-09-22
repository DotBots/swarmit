import logging
import threading
import time
from unittest.mock import PropertyMock, patch

import pytest
from marilib.model import GatewayInfo, MariGateway

from swarmit.testbed.controller import (
    Chunk,
    Controller,
    ControllerSettings,
    DeviceInfo,
    NodeStatus,
    ResetLocation,
    StaleBootloaderError,
    StartOtaData,
    format_reset_cause,
    format_uptime,
    generate_info,
    generate_status,
    image_mismatches,
)
from swarmit.testbed.logger import setup_logging
from swarmit.testbed.ota import BlockOTASettings
from swarmit.testbed.protocol import (
    OTA_PROTOCOL_VERSION_LEGACY,
    FaultType,
    StatusType,
)
from swarmit.tests.utils import (
    ChunkLossStrategy,
    MarilibMQTTAdapterMock,
    MarilibSerialAdapterMock,
    SwarmitNode,
)


def _fast_ota_settings(*args, **kwargs) -> BlockOTASettings:
    """Pacing stand-in for tests: no inter-chunk delay, short report window.

    The real derivation paces sends at the radio's downlink rate, which would
    stretch these transfers to tens of seconds. The mocked transport delivers
    instantly, so here pacing only costs wall clock.
    """
    return BlockOTASettings(inter_chunk_delay=0.0, report_timeout=0.02)


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_basic():
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    assert sorted(controller.known_devices.keys()) == [
        f"{node.address:08X}" for node in nodes
    ]
    assert sorted(controller.ready_devices) == [
        f"{node.address:08X}" for node in nodes
    ]
    assert sorted(controller.running_devices) == []
    assert sorted(controller.resetting_devices) == []

    nodes[0].status = StatusType.Running
    time.sleep(0.5)
    assert sorted(controller.ready_devices) == [f"{nodes[1].address:08X}"]
    assert sorted(controller.running_devices) == [f"{nodes[0].address:08X}"]
    assert sorted(controller.resetting_devices) == []

    nodes[1].status = StatusType.Resetting
    time.sleep(0.5)
    assert sorted(controller.ready_devices) == []
    assert sorted(controller.resetting_devices) == [f"{nodes[1].address:08X}"]
    assert sorted(controller.running_devices) == [f"{nodes[0].address:08X}"]

    nodes[0].enabled = False
    time.sleep(1.5)

    assert list(controller.known_devices.keys()) == [f"{nodes[1].address:08X}"]

    controller.terminate()


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_start_broadcast():
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    controller.start()
    time.sleep(0.3)
    assert all([node.status == StatusType.Running for node in nodes]) is True


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_start_unicast():
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    node3 = SwarmitNode(
        address=0x03, status=StatusType.Running, adapter=test_adapter
    )
    nodes.append(node3)

    for node in nodes:
        test_adapter.add_node(node)

    assert sorted(controller.known_devices.keys()) == [
        f"{node.address:08X}" for node in nodes
    ]

    controller.status_data = {}
    controller.start(devices=["00000001", "00000003"])
    time.sleep(0.3)
    assert nodes[0].status == StatusType.Running
    assert nodes[1].status == StatusType.Bootloader
    assert nodes[2].status == StatusType.Running


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibMQTTAdapter",
    MarilibMQTTAdapterMock,
)
def test_controller_start_broadcast_cloud_adapter():
    controller = Controller(
        ControllerSettings(
            adapter="cloud", network_id=42, adapter_wait_timeout=0.1
        )
    )
    controller.interface.mari.gateways = {
        0: MariGateway(info=GatewayInfo(address=0, network_id=42))
    }
    test_adapter = controller.interface.mari.mqtt_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    controller.start()
    time.sleep(0.3)
    assert all([node.status == StatusType.Running for node in nodes]) is True


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_stop_broadcast():
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(
            address=addr, status=StatusType.Running, adapter=test_adapter
        )
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    controller.stop()
    time.sleep(0.3)
    assert (
        all([node.status == StatusType.Bootloader for node in nodes]) is True
    )


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_stop_unicast():
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(
            address=addr, status=StatusType.Running, adapter=test_adapter
        )
        for addr in [0x01, 0x02]
    ]
    node3 = SwarmitNode(address=0x03, adapter=test_adapter)
    nodes.append(node3)

    for node in nodes:
        test_adapter.add_node(node)

    assert sorted(controller.known_devices.keys()) == [
        f"{node.address:08X}" for node in nodes
    ]

    controller.stop(devices=["00000001", "00000003"])
    time.sleep(0.3)
    assert nodes[0].status == StatusType.Bootloader
    assert nodes[1].status == StatusType.Running
    assert nodes[2].status == StatusType.Bootloader


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_status(capsys):
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    controller.status(timeout=0.1)
    out, _ = capsys.readouterr()
    assert "No device found" in out

    node1 = SwarmitNode(address=0x01, adapter=test_adapter, battery=2950)
    node2 = SwarmitNode(address=0x02, adapter=test_adapter, battery=2100)
    node3 = SwarmitNode(address=0x03, adapter=test_adapter, battery=1500)
    nodes = [node1, node2, node3]
    for node in nodes:
        test_adapter.add_node(node)

    controller.status(timeout=0.1)
    out, _ = capsys.readouterr()
    assert "3 devices found" in out
    assert f"{node1.address:08X}" in out
    assert f"{node2.address:08X}" in out
    assert f"{node3.address:08X}" in out
    assert f"{2950/1000:.2f}V" in out
    assert f"{2100/1000:.2f}V" in out
    assert f"{1500/1000:.2f}V" in out


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibMQTTAdapter",
    MarilibMQTTAdapterMock,
)
def test_controller_status_adapter_cloud(capsys):
    controller = Controller(
        ControllerSettings(
            adapter="cloud", network_id=42, adapter_wait_timeout=0.1
        )
    )
    controller.interface.mari.gateways = {
        0: MariGateway(info=GatewayInfo(address=0, network_id=42))
    }
    test_adapter = controller.interface.mari.mqtt_interface
    controller.status(timeout=0.1)
    out, _ = capsys.readouterr()
    assert "No device found" in out

    node1 = SwarmitNode(address=0x01, adapter=test_adapter)
    node2 = SwarmitNode(address=0x02, adapter=test_adapter, battery=2100)
    node3 = SwarmitNode(address=0x03, adapter=test_adapter, battery=1500)
    nodes = [node1, node2, node3]
    for node in nodes:
        test_adapter.add_node(node)

    controller.status(timeout=0.1)
    time.sleep(0.3)
    out, _ = capsys.readouterr()
    assert "3 devices found" in out
    assert f"{node1.address:08X}" in out
    assert f"{node2.address:08X}" in out
    assert f"{node3.address:08X}" in out
    assert f"{2500/1000:.2f}V" in out
    assert f"{2100/1000:.2f}V" in out
    assert f"{1500/1000:.2f}V" in out


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_reset():
    controller = Controller(
        ControllerSettings(
            devices=["00000001", "00000002"], adapter_wait_timeout=0.1
        )
    )
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)
    locations = {
        "00000001": ResetLocation(pos_x=1000000, pos_y=2000),
        "00000002": ResetLocation(pos_x=2000000, pos_y=1000),
    }
    controller.reset(locations=locations)
    time.sleep(0.3)
    for node in nodes:
        assert node.status == StatusType.Resetting
    controller.stop()
    time.sleep(0.3)
    assert (
        all([node.status == StatusType.Bootloader for node in nodes]) is True
    )


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_reset_not_ready():
    controller = Controller(
        ControllerSettings(
            devices=["00000001", "00000002"], adapter_wait_timeout=0.1
        )
    )
    test_adapter = controller.interface.mari.serial_interface
    node1 = SwarmitNode(address=0x01, adapter=test_adapter)
    node2 = SwarmitNode(
        address=0x02, status=StatusType.Running, adapter=test_adapter
    )
    nodes = [node1, node2]

    for node in nodes:
        test_adapter.add_node(node)
    locations = {
        "00000001": ResetLocation(pos_x=1000000, pos_y=2000),
        "00000002": ResetLocation(pos_x=2000000, pos_y=1000),
    }
    controller.reset(locations=locations)
    time.sleep(0.3)
    assert node1.status == StatusType.Resetting
    assert node2.status == StatusType.Running

    controller.stop()
    time.sleep(0.3)
    assert node1.status == StatusType.Bootloader
    assert node2.status == StatusType.Bootloader


@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_monitor(caplog):
    caplog.set_level(logging.INFO)
    setup_logging()
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))

    controller.monitor(run_forever=False, timeout=0.1)
    assert "Monitoring testbed" in caplog.text

    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)
        node.start_log_event_task()

    controller.monitor(run_forever=False, timeout=0.1)
    assert "Monitoring testbed" in caplog.text
    for node in nodes:
        assert f"Node {node.address:08X} log event" in caplog.text
    controller.terminate()


@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_monitor_single_device(caplog):
    caplog.set_level(logging.INFO)
    setup_logging()
    controller = Controller(
        ControllerSettings(devices=["00000001"], adapter_wait_timeout=0.1)
    )

    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)
        node.start_log_event_task()

    controller.monitor(run_forever=False, timeout=0.1)
    assert "Monitoring testbed" in caplog.text
    assert "Node 00000001 log event" in caplog.text
    assert "Node 00000002 log event" not in caplog.text
    controller.terminate()


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_send_message_unicast(capsys):
    controller = Controller(
        ControllerSettings(
            devices=["00000001", "00000003"], adapter_wait_timeout=0.1
        )
    )
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(
            address=addr, status=StatusType.Running, adapter=test_adapter
        )
        for addr in [0x01, 0x02]
    ]
    node3 = SwarmitNode(address=0x03, adapter=test_adapter)
    nodes.append(node3)
    for node in nodes:
        test_adapter.add_node(node)

    controller.send_message("Hello robot!")
    out, _ = capsys.readouterr()
    assert "Node 00000001 received message: Hello robot!" in out
    assert "Node 00000003 received message: Hello robot!" not in out


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_send_message_broadcast(capsys):
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(
            address=addr, status=StatusType.Running, adapter=test_adapter
        )
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    controller.send_message("Hello robot!")
    out, _ = capsys.readouterr()
    for node in ["00000001", "00000002"]:
        assert f"Node {node} received message: Hello robot!" in out


def _calibration_messages():
    from swarmit.tests.lh2_wire_fixture import MESSAGE_HEX

    return [bytes.fromhex(h) for h in MESSAGE_HEX]


def _send_calibration(blob, ready=("00000001",), devices=None):
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    try:
        with patch.object(
            type(controller),
            "ready_devices",
            new_callable=PropertyMock,
            return_value=list(ready),
        ):
            with patch.object(controller, "send_payload") as send_payload_mock:
                controller.send_lh2_calibration(blob, devices)
    finally:
        controller.terminate()
    return send_payload_mock


@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
@patch("swarmit.testbed.controller.COMMAND_MAX_ATTEMPTS", 1)
def test_controller_sends_calibration_only_to_the_devices_named():
    # No READY device, which would otherwise mean a broadcast.
    send_payload_mock = _send_calibration(
        b"".join(_calibration_messages()), ready=(), devices=["0000000a"]
    )

    assert [call.args[0] for call in send_payload_mock.call_args_list] == [
        0xA,
        0xA,
    ]


@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
@patch("swarmit.testbed.controller.COMMAND_MAX_ATTEMPTS", 1)
def test_controller_sends_one_calibration_message_per_station():
    messages = _calibration_messages()

    send_payload_mock = _send_calibration(b"".join(messages))

    assert send_payload_mock.call_count == 2
    for call, message in zip(send_payload_mock.call_args_list, messages):
        # ready_devices is set, so unicast to "00000001" -> 0x1.
        assert call.args[0] == 0x1
        assert bytes(call.args[1].to_bytes()) == message
    first = send_payload_mock.call_args_list[0].args[1]
    assert first.homography_count == 2
    assert (first.valid_x_max, first.valid_y_max) == (3330, 4000)
    assert first.site_name == b"c405-arena" + bytes(6)
    assert bytes(first.calibration_id).hex() == "ac893d2d85e3068c"


@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
@patch("swarmit.testbed.controller.COMMAND_MAX_ATTEMPTS", 1)
@pytest.mark.parametrize(
    "blob, match",
    [
        (b"\x00" * 83, "expected N x 84 bytes"),
        # The retired int32 format, a count byte and one matrix.
        (bytes([1]) + bytes(36), "expected N x 84 bytes"),
        (b"", "expected N x 84 bytes"),
    ],
    ids=["short", "int32-format", "empty"],
)
def test_controller_refuses_a_calibration_of_the_wrong_size(blob, match):
    with pytest.raises(ValueError, match=match):
        _send_calibration(blob)


@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
@patch("swarmit.testbed.controller.COMMAND_MAX_ATTEMPTS", 1)
def test_controller_refuses_messages_that_are_not_one_push():
    first, second = _calibration_messages()
    with pytest.raises(ValueError, match="count field"):
        _send_calibration(first)
    with pytest.raises(ValueError, match="indices 0 to N-1"):
        _send_calibration(second + first)
    other_site = second[:60] + b"elsewhere".ljust(16, b"\x00") + second[76:]
    with pytest.raises(ValueError, match="site fields differ"):
        _send_calibration(first + other_site)


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch("swarmit.testbed.controller.derive_block_settings", _fast_ota_settings)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_broadcast():
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]
    assert ota_data["missed"] == []

    for node in nodes:
        assert node.status == StatusType.Programming

    result = controller.transfer(firmware, ota_data["acked"])
    time.sleep(0.3)
    assert all([transfer.success for transfer in result.values()]) is True


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch("swarmit.testbed.controller.derive_block_settings", _fast_ota_settings)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_broadcast_verbose():
    controller = Controller(
        ControllerSettings(adapter_wait_timeout=0.1, verbose=True)
    )
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]
    assert ota_data["missed"] == []

    for node in nodes:
        assert node.status == StatusType.Programming

    result = controller.transfer(firmware, ota_data["acked"])
    time.sleep(0.3)
    assert all([transfer.success for transfer in result.values()]) is True


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch("swarmit.testbed.controller.derive_block_settings", _fast_ota_settings)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_unicast():
    controller = Controller(
        ControllerSettings(devices=["00000001"], adapter_wait_timeout=0.1)
    )
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    firmware = b"\x00" * 2**16 + b"\x01" * 1234

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == ["00000001"]
    assert ota_data["missed"] == []

    assert nodes[0].status == StatusType.Programming
    assert nodes[1].status == StatusType.Bootloader

    result = controller.transfer(firmware, ota_data["acked"])
    time.sleep(0.3)
    assert all([transfer.success for transfer in result.values()]) is True
    # The untargeted bot was never written to.
    assert nodes[1].received_chunks == set()


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch("swarmit.testbed.controller.derive_block_settings", _fast_ota_settings)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_repairs_lost_chunks():
    """A chunk lost on the downlink is repaired from the block report."""
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    # node1 misses chunk 5 twice, then accepts the repair broadcast.
    node1 = SwarmitNode(
        address=0x01,
        loss_strategy=ChunkLossStrategy(drop_index=5, drop_count=2),
        adapter=test_adapter,
    )
    # node2 never receives chunk 5, so its image stays incomplete.
    node2 = SwarmitNode(
        address=0x02,
        loss_strategy=ChunkLossStrategy(drop_index=5, drop_count=10_000),
        adapter=test_adapter,
    )
    nodes = [node1, node2]
    for node in nodes:
        test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]

    result = controller.transfer(firmware, ota_data["acked"])
    assert result["00000001"].success is True
    assert result["00000002"].success is False
    # The repair actually delivered the chunk rather than giving up on it.
    assert 5 in node1.received_chunks
    assert 5 not in node2.received_chunks


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch("swarmit.testbed.controller.derive_block_settings", _fast_ota_settings)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_finalize_mismatch_fails():
    """A complete delivery whose image SHA does not match is not a success."""
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x01, ota_should_fail=True, adapter=test_adapter
    )
    test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    result = controller.transfer(firmware, ota_data["acked"])
    # Every chunk arrived, but the device rejected the whole-image hash.
    assert len(node.received_chunks) == node.total_chunks
    assert result["00000001"].success is False


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch("swarmit.testbed.controller.derive_block_settings", _fast_ota_settings)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_refuses_stale_bootloader():
    """A bot that never announces the block protocol aborts the flash."""
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x01,
        ota_protocol_version=OTA_PROTOCOL_VERSION_LEGACY,
        adapter=test_adapter,
    )
    test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == ["00000001"]
    assert controller.stale_bootloaders(ota_data["acked"]) == ["00000001"]

    with pytest.raises(StaleBootloaderError) as exc:
        controller.transfer(firmware, ota_data["acked"])
    assert "00000001" in str(exc.value)
    assert "flash-swarmit-sandbox" in str(exc.value)
    # Aborted before any chunk went on the wire.
    assert node.received_chunks == set()


def test_controller_chunk_repr():
    chunk = Chunk(index=42, size=128, acked=True, retries=2)
    assert (
        repr(chunk)
        == "{'index': 42, 'size': 128, 'acked': True, 'retries': 2}"
    )


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_REFRESH_INTERVAL", 0.05)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_device_info_fetched_once_per_change():
    """The generation counter is what bounds device-info traffic.

    A bot is read once when first seen and then never again until its
    generation moves, no matter how many status frames arrive in between.
    """
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x01,
        adapter=test_adapter,
        info_gen=3,
        image_name="lakers-sandbox.bin",
        image_version="0.9.0",
    )
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)
    assert controller.status_data[addr] is not None

    # First read lands on its own, with no explicit request from the caller.
    deadline = time.time() + 3
    while time.time() < deadline and not controller.status_data[addr].info:
        time.sleep(0.01)
    info = controller.status_data[addr].info
    assert info is not None
    assert info.info_gen == 3
    assert info.image_name == "lakers-sandbox.bin"
    assert info.image_version == "0.9.0"
    assert info.image_label == "lakers-sandbox.bin"

    # Many more status frames go by; none of them costs a device-info round.
    asked_once = node.device_info_requests
    assert asked_once >= 1
    time.sleep(0.8)
    assert node.device_info_requests == asked_once
    assert controller.stale_device_info() == []

    # The bot reboots: the counter moves and exactly one more read follows.
    node.info_gen = 4
    node.boot_count = 4
    deadline = time.time() + 3
    while (
        time.time() < deadline
        and controller.status_data[addr].info.info_gen != 4
    ):
        time.sleep(0.01)
    assert controller.status_data[addr].info.info_gen == 4
    assert controller.status_data[addr].info.boot_count == 4
    assert node.device_info_requests == asked_once + 1

    node.stop()
    controller.terminate()


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_REFRESH_INTERVAL", 0.02)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_firmware_without_device_info_is_never_asked():
    """A zero generation counter identifies firmware that cannot answer.

    That is a property of the device rather than a guess from a timeout, so it
    is recognised on the first status frame and never costs a request - where
    an attempt cap would have spent several broadcasts learning it, every
    session.
    """
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x02,
        adapter=test_adapter,
        info_gen=0,
        answers_device_info=False,
    )
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)

    assert controller.stale_device_info() == []
    for _ in range(3):
        controller._info_last_broadcast = 0.0
        controller._refresh_stale_device_info()
    assert node.device_info_requests == 0
    assert controller.status_data[addr].info is None

    # Firmware that does report a counter is asked, even having been quiet.
    node.info_gen = 9
    deadline = time.time() + 3
    while (
        time.time() < deadline and controller.status_data[addr].info_gen != 9
    ):
        time.sleep(0.01)
    assert controller.stale_device_info() == [addr]

    node.stop()
    controller.terminate()


def _node_with_image(digest: str, name: str = "", gen: int = 1):
    """A cached status entry carrying a device-info block, for the
    majority-mismatch tests. Built directly rather than over the mock
    transport: what is under test is the comparison, not the wire."""
    return NodeStatus(
        info_gen=gen,
        info=DeviceInfo(info_gen=gen, image_digest=digest, image_name=name),
    )


def test_image_mismatches_all_agree():
    data = {
        "AA": _node_with_image("3f9a2c81d4e5b607"),
        "BB": _node_with_image("3f9a2c81d4e5b607"),
        "CC": _node_with_image("3f9a2c81d4e5b607"),
    }
    majority, odd = image_mismatches(data)
    assert majority == "3f9a2c81d4e5b607"
    assert odd == []


def test_image_mismatches_flags_the_odd_one_out():
    data = {
        "AA": _node_with_image("3f9a2c81d4e5b607", "lakers-sandbox"),
        "BB": _node_with_image("3f9a2c81d4e5b607", "lakers-sandbox"),
        "CC": _node_with_image("9e4c1a70d2b83f56", "move-and-blink"),
    }
    majority, odd = image_mismatches(data)
    assert majority == "3f9a2c81d4e5b607"
    assert [addr for addr, _ in odd] == ["CC"]
    assert odd[0][1].image_name == "move-and-blink"


def test_image_mismatches_compares_digests_not_names():
    # Two bots claiming the same name over different bytes is exactly why the
    # digest is the identity and the name is decoration.
    data = {
        "AA": _node_with_image("1111111111111111", "app.bin"),
        "BB": _node_with_image("1111111111111111", "app.bin"),
        "CC": _node_with_image("2222222222222222", "app.bin"),
    }
    majority, odd = image_mismatches(data)
    assert majority == "1111111111111111"
    assert [addr for addr, _ in odd] == ["CC"]


def test_image_mismatches_ignores_devices_that_have_not_answered():
    # Unknown is not the same as different: a bot that has not reported device
    # info must not be counted as disagreeing, or every rollout would show a
    # spurious callout while the fleet is still being read.
    data = {
        "AA": _node_with_image("3f9a2c81d4e5b607"),
        "BB": _node_with_image("3f9a2c81d4e5b607"),
        "CC": NodeStatus(),  # never answered
    }
    majority, odd = image_mismatches(data)
    assert majority == "3f9a2c81d4e5b607"
    assert odd == []


def test_image_mismatches_needs_at_least_two_known_devices():
    # A single bot is trivially its own majority; calling that a match or a
    # mismatch is meaningless either way.
    assert image_mismatches({"AA": _node_with_image("aa")}) == ("", [])
    assert image_mismatches({}) == ("", [])


def test_image_label_distinguishes_no_image_from_unknown():
    # Found on hardware: a bot that has never been flashed over the air
    # reports a zeroed record, which read as an image whose digest was
    # sixteen zeros.
    blank = DeviceInfo(image_digest="0" * 16, image_size=0)
    assert blank.has_image is False
    assert blank.image_label == "none"

    real = DeviceInfo(image_digest="d1e1d9804851a855", image_size=9844)
    assert real.has_image is True
    assert real.image_label == "d1e1d9804851a855"
    assert (
        DeviceInfo(
            image_digest="d1e1d9804851a855",
            image_size=9844,
            image_name="sample.bin",
        ).image_label
        == "sample.bin"
    )


def test_format_uptime():
    assert format_uptime(41) == "41s"
    assert format_uptime(204) == "3m 24s"
    assert format_uptime(4324) == "1h 12m 04s"


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_TIMEOUT", 1.0)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_explicit_fetch_asks_even_when_the_generation_matches():
    """`info` must re-read, not trust the cache.

    Not everything in the block is inventory: `uptime_s` moves every second,
    so an unchanged generation counter does not mean the values are still
    true. An explicit fetch that short-circuits on a fresh-looking cache
    renders the uptime sampled at the previous fetch.
    """
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(address=0x11, adapter=test_adapter, info_gen=7)
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)

    controller.fetch_device_info([addr])
    first = node.device_info_requests
    assert first >= 1
    assert controller.status_data[addr].info is not None

    # Generation has not moved, so the background sweep would correctly stay
    # quiet - but an explicit ask must still go out.
    assert controller.stale_device_info() == []
    controller.fetch_device_info([addr])
    assert node.device_info_requests > first
    # And the demand is released, so the sweep does not keep broadcasting.
    assert controller._info_forced == set()

    node.stop()
    controller.terminate()


def test_device_info_reply_survives_a_concurrent_timeout():
    """The RX thread must not raise when a device times out mid-callback.

    `cleanup_inactive` deletes entries from another thread; a check-then-act
    on status_data raises KeyError in that window.
    """
    from unittest.mock import MagicMock

    from dotbot_utils.protocol import Packet

    from swarmit.testbed.protocol import PayloadDeviceInfo

    controller = Controller.__new__(Controller)
    controller.logger = MagicMock()
    controller.settings = ControllerSettings()
    controller.status_data = {}
    controller._device_info = {}
    controller._info_backoff = {}
    controller._info_next_try = {}
    controller._info_gen_seen = {}
    controller._info_forced = set()
    controller._block_transfer = None
    controller.start_ota_data = StartOtaData()
    controller._ota_versions = {}
    controller._log_event_listeners = []
    controller._log_listeners_lock = threading.Lock()

    header = MagicMock()
    header.source = 0x22
    packet = Packet.from_payload(PayloadDeviceInfo(info_version=1, info_gen=3))
    # status_data is deliberately empty: the device timed out between the
    # request going out and this reply arriving.
    controller.on_frame_received(header, packet)

    assert controller._device_info["00000022"].info_gen == 3


def test_reset_reason_row_drops_a_redundant_decode():
    """The raw row's decode should say more than the friendly cause, or nothing.

    A single-bit RESETREAS decodes to exactly the friendly label, so printing
    both put "soft-reset" under "soft-reset". A multi-bit value genuinely says
    more and keeps its decode.
    """
    from swarmit.testbed.protocol import decode_reset_reason

    single = NodeStatus(reset_reason=0x08)
    assert decode_reset_reason(0x08) == format_reset_cause(single)

    multi = NodeStatus(reset_reason=0x1C)
    assert decode_reset_reason(0x1C) == "ctrl-ap+soft-reset+lockup"
    assert format_reset_cause(multi) == "lockup"
    assert decode_reset_reason(0x1C) != format_reset_cause(multi)


def test_a_hang_is_not_reported_as_a_crash():
    """A watchdog timeout raised no fault, so "crashed" would misdirect.

    The operator-facing distinction is the point of the whole change: "hung"
    plus an address sends someone to the function that overran, where
    "crashed" sends them looking for a fault status that was never populated.
    """
    hung = NodeStatus(
        reset_reason=0x2,  # watchdog0
        fault=FaultType.WatchdogTimeout.value,
        pc=0x0001_3A4E,
    )
    assert format_reset_cause(hung) == "hung (watchdog0 pc=0x00013a4e)"

    crashed = NodeStatus(
        reset_reason=0x2,
        fault=FaultType.HardFault.value,
        pc=0x0001_3A4E,
    )
    assert format_reset_cause(crashed).startswith(
        "crashed (watchdog0 HardFault"
    )

    # Firmware predating the capture, and the case where the handler could not
    # run: WDT0 fired with nothing latched. Still a crash, still no address.
    silent = NodeStatus(reset_reason=0x2)
    assert format_reset_cause(silent) == "crashed (watchdog0)"


def test_info_panel_does_not_repeat_the_boot_reason():
    """The Matter vocabulary is for a bridge, not for this panel.

    `Last reset` and `reset_reason` already answer why it booted, from the
    authoritative register, so a third coarse rendering is noise.
    """
    from rich.console import Console

    data = {
        "AA": NodeStatus(
            reset_reason=0x08,
            last_updated_at=time.time(),
            info_gen=4,
            info=DeviceInfo(info_gen=4, boot_count=4, uptime_s=12),
        )
    }
    console = Console(width=120, no_color=True)
    with console.capture() as cap:
        console.print(generate_info(data, []))
    out = cap.get()

    assert "boot #4" in out
    assert "SoftwareReset" not in out
    # The friendly cause still appears exactly once.
    assert out.count("soft-reset") == 1


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_TIMEOUT", 0.4)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_fetch_accepts_a_lowercase_device_argument():
    """`-d` is user input; status_data keys are upper-cased by addr_to_hex.

    Intersecting the two without normalising made the loop exit on the first
    pass without sending anything.
    """
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(address=0xAB, adapter=test_adapter, info_gen=2)
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)

    controller.fetch_device_info([addr.lower()])
    assert node.device_info_requests >= 1

    node.stop()
    controller.terminate()


def test_unusable_device_info_is_dropped_and_does_not_reset_backoff():
    """A reply that cannot resolve staleness must not reset the attempt cap.

    A truncated body zero-fills to `info_version = 0`. Caching it, or clearing
    the counter for it, would leave a device that always answers unusably being
    re-broadcast for the life of the session - a cap that never caps.
    """
    from unittest.mock import MagicMock

    from dotbot_utils.protocol import Packet

    from swarmit.testbed.protocol import PayloadDeviceInfo

    controller = Controller.__new__(Controller)
    controller.logger = MagicMock()
    controller.settings = ControllerSettings()
    controller.status_data = {"00000033": NodeStatus(info_gen=7)}
    controller._device_info = {}
    controller._info_backoff = {"00000033": 4.0}
    controller._info_next_try = {"00000033": 0.0}
    controller._info_gen_seen = {}
    controller._info_forced = set()
    controller._block_transfer = None
    controller.start_ota_data = StartOtaData()
    controller._ota_versions = {}
    controller._log_event_listeners = []
    controller._log_listeners_lock = threading.Lock()

    header = MagicMock()
    header.source = 0x33
    controller.on_frame_received(
        header, Packet.from_payload(PayloadDeviceInfo(info_version=0))
    )

    assert "00000033" not in controller._device_info
    # The backoff survives, so an unusable reply does not reset the schedule.
    assert controller._info_backoff["00000033"] == 4.0


def test_matching_generation_clears_the_backoff():
    from unittest.mock import MagicMock

    from dotbot_utils.protocol import Packet

    from swarmit.testbed.protocol import PayloadDeviceInfo

    controller = Controller.__new__(Controller)
    controller.logger = MagicMock()
    controller.settings = ControllerSettings()
    controller.status_data = {"00000044": NodeStatus(info_gen=7)}
    controller._device_info = {}
    controller._info_backoff = {"00000044": 4.0}
    controller._info_next_try = {"00000044": 0.0}
    controller._info_gen_seen = {}
    controller._info_forced = set()
    controller._block_transfer = None
    controller.start_ota_data = StartOtaData()
    controller._ota_versions = {}
    controller._log_event_listeners = []
    controller._log_listeners_lock = threading.Lock()

    header = MagicMock()
    header.source = 0x44
    controller.on_frame_received(
        header,
        Packet.from_payload(PayloadDeviceInfo(info_version=1, info_gen=7)),
    )

    assert controller._device_info["00000044"].info_gen == 7
    assert "00000044" not in controller._info_backoff


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_REFRESH_INTERVAL", 1.0)
@patch("swarmit.testbed.controller.DEVICE_INFO_BACKOFF_MAX", 8.0)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_unanswered_device_backs_off_but_is_never_written_off():
    """A device that should answer and does not is asked less, not never.

    It reports a real generation counter, so it is not old firmware - it is
    busy. Giving up would leave it showing as unknown until something else
    moved its counter; backing off bounds the traffic instead.
    """
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x55,
        adapter=test_adapter,
        info_gen=4,
        answers_device_info=False,
    )
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)

    seen = []
    for _ in range(5):
        controller._info_last_broadcast = 0.0
        controller._info_next_try[addr] = 0.0  # pretend the wait elapsed
        controller._refresh_stale_device_info()
        seen.append(controller._info_backoff[addr])

    # Doubles, then holds at the ceiling rather than growing without bound.
    assert seen == [1.0, 2.0, 4.0, 8.0, 8.0]
    # Still a candidate: it is never written off the way a cap would.
    controller._info_next_try[addr] = 0.0
    assert controller.stale_device_info() == [addr]

    node.stop()
    controller.terminate()


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_REFRESH_INTERVAL", 1.0)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_a_generation_change_cancels_the_backoff():
    """A reboot or a flash is exactly when the answer is wanted soonest."""
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x66,
        adapter=test_adapter,
        info_gen=4,
        answers_device_info=False,
    )
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)

    controller._info_last_broadcast = 0.0
    controller._refresh_stale_device_info()
    assert controller._info_backoff[addr] > 0

    node.info_gen = 5
    deadline = time.time() + 3
    while (
        time.time() < deadline and controller.status_data[addr].info_gen != 5
    ):
        time.sleep(0.01)

    assert addr not in controller._info_backoff
    assert controller.stale_device_info() == [addr]

    node.stop()
    controller.terminate()


def _render(renderable, width: int = 200) -> str:
    """Capture a rich renderable as plain text, wide enough not to wrap."""
    from rich.console import Console

    console = Console(width=width, no_color=True)
    with console.capture() as cap:
        console.print(renderable)
    return cap.get()


def test_info_panel_always_names_the_calibration_state():
    """Three facts, three strings - never the absence of a row.

    Dropping the row when device info had not landed made "we never asked"
    look exactly like "this bot is uncalibrated", which are opposite actions
    for the operator: wait, versus go and re-provision it.
    """
    never_asked = {"AA": NodeStatus(info=None)}
    assert "unknown (no device info)" in _render(
        generate_info(never_asked, [])
    )

    uncalibrated = {"AA": NodeStatus(info=DeviceInfo(info_version=1))}
    out = _render(generate_info(uncalibrated, []))
    assert "LH2 calibration" in out
    assert "uncalibrated" in out

    calibrated = {
        "AA": NodeStatus(
            info=DeviceInfo(
                info_version=1, lh2_homography_count=2, lh2_flags=0b11
            )
        )
    }
    assert "2 basestations (valid, from flash)" in _render(
        generate_info(calibrated, [])
    )


def test_info_panel_always_shows_the_site_and_the_id():
    held = {
        "AA": NodeStatus(
            info=DeviceInfo(
                info_version=2,
                lh2_homography_count=2,
                lh2_site_name="c405-arena",
                lh2_calibration_id="ac893d2d85e3068c",
            )
        )
    }
    out = _render(generate_info(held, []))
    assert "c405-arena" in out
    assert "ac893d2d85e3068c" in out

    empty = {"AA": NodeStatus(info=DeviceInfo(info_version=2))}
    out = _render(generate_info(empty, []))
    assert "site" in out and "none" in out

    old = {"AA": NodeStatus(info=DeviceInfo(info_version=1))}
    assert "firmware predates it" in _render(generate_info(old, []))


def test_a_single_basestation_is_not_pluralised():
    info = DeviceInfo(info_version=1, lh2_homography_count=1, lh2_flags=0b01)
    assert info.lh2_summary == "1 basestation (valid)"


def test_position_says_no_fix_instead_of_the_origin():
    """(0, 0) is what an unlocated bot reports, not where it is.

    The calibrated square starts two of its own widths from the origin, so a
    located bot cannot report (0, 0) - printing it as a coordinate claimed a
    fix that never happened, on both surfaces.
    """
    unlocated = {"AA": NodeStatus(last_updated_at=time.time())}
    assert "no fix" in _render(generate_info(unlocated, []))
    assert "no fix" in _render(generate_status(unlocated))

    located = {"AA": NodeStatus(pos_x=1200, pos_y=1300)}
    assert "1200, 1300" in _render(generate_info(located, []))
    assert "1200, 1300" in _render(generate_status(located))


def test_position_tells_uncalibrated_apart_from_a_missing_fix():
    """Two ways to be nowhere, two different things to go and do.

    Both printed `no fix`, which sent the operator to inspect the lighthouses
    for a bot that had never been calibrated - where no amount of coverage
    would have changed the cell. Device info already says which it is, so the
    cell says it too, in the same word as the `LH2 calibration` row.
    """
    uncalibrated = {"AA": NodeStatus(info=DeviceInfo(info_version=1))}
    out = _render(generate_info(uncalibrated, []))
    assert "uncalibrated" in out
    assert "no fix" not in out

    # A fleet that disagrees keeps the LH2 column, so calibration is not also
    # named in the header line and the Position cell is the only place the
    # word can come from.
    fleet = {
        "AA": NodeStatus(info=DeviceInfo(info_version=1)),
        "BB": NodeStatus(
            info=DeviceInfo(
                info_version=1, lh2_homography_count=2, lh2_flags=0b11
            )
        ),
    }
    out = _render(generate_status(fleet))
    assert "uncalibrated" in out  # AA was never calibrated
    assert "no fix" in out  # BB is calibrated and out of coverage


def test_position_stays_no_fix_when_device_info_has_not_landed():
    """An unknown reason gets the honest label, not a guessed one.

    Until device info arrives the controller cannot tell an uncalibrated bot
    from one out of coverage, and `no fix` is still literally true - so it
    stays, on both surfaces, rather than growing a fourth string.
    """
    unknown = {"AA": NodeStatus(info=None, last_updated_at=time.time())}
    assert "no fix" in _render(generate_info(unknown, []))
    assert "no fix" in _render(generate_status(unknown))


def test_status_collapses_calibration_when_the_fleet_agrees():
    """One arena, one calibration run - so normally one value, stated once.

    Same treatment as the sandbox-firmware column: spending table width to
    repeat one string per row is what stops the fleet laying out side by side.
    """
    info = DeviceInfo(info_version=1, lh2_homography_count=2, lh2_flags=0b11)
    fleet = {
        "AA": NodeStatus(info=info),
        "BB": NodeStatus(info=info),
    }
    out = _render(generate_status(fleet))

    assert "LH2 calibration: 2 basestations (valid, from flash)" in out
    # Stated once above the table, not once per row.
    assert out.count("2 basestations") == 1


def test_status_shows_the_calibration_column_when_the_fleet_disagrees():
    """A bot out of step with the fleet is the case worth a column.

    The cell carries the count, not the summary: spelled out per row it wraps
    to four lines and the column stops being readable exactly when it matters.
    "none" and "-" are the image cell's vocabulary, meaning the same two
    things here - answered with nothing, versus never answered.
    """
    fleet = {
        "AA": NodeStatus(
            info=DeviceInfo(
                info_version=1, lh2_homography_count=2, lh2_flags=0b11
            )
        ),
        "BB": NodeStatus(info=DeviceInfo(info_version=1)),
        "CC": NodeStatus(info=None),
    }
    out = _render(generate_status(fleet))

    assert "LH2 calibration: " not in out  # no header line
    assert "LH2" in out  # the column
    # Compact, so it does not wrap: no row spells the summary out.
    assert "2 basestations" not in out


def test_status_compares_calibration_on_the_summary_not_the_count():
    """Same count, different provenance, is still a fleet that disagrees.

    Comparing the rendered cell would collapse these two into one header line
    asserting a provenance only one of them has.
    """
    fleet = {
        "AA": NodeStatus(
            info=DeviceInfo(
                info_version=1, lh2_homography_count=2, lh2_flags=0b11
            )
        ),
        "BB": NodeStatus(
            info=DeviceInfo(
                info_version=1, lh2_homography_count=2, lh2_flags=0b01
            )
        ),
    }
    assert "LH2 calibration: " not in _render(generate_status(fleet))


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 5)
@patch("swarmit.testbed.controller.DEVICE_INFO_TIMEOUT", 1.0)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_calibration_and_position_reach_the_panel_from_the_wire():
    """End to end: an emulated bot's LH2 state survives the round trip.

    The rendering tests above build `DeviceInfo` directly, so they would still
    pass if `from_payload` stopped copying the fields. This drives a node over
    the mock adapter instead, so the values are parsed off a real packet.
    """
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x77,
        adapter=test_adapter,
        info_gen=3,
        lh2_homography_count=2,
        lh2_flags=0b11,
        pos_x=1200,
        pos_y=1300,
    )
    test_adapter.add_node(node)
    addr = f"{node.address:08X}"

    deadline = time.time() + 3
    while time.time() < deadline and controller.status_data.get(addr) is None:
        time.sleep(0.01)

    controller.fetch_device_info([addr])
    info = controller.status_data[addr].info
    assert info is not None
    assert info.lh2_homography_count == 2
    assert info.lh2_flags == 0b11

    out = _render(generate_info(controller.status_data, []))
    assert "2 basestations (valid, from flash)" in out
    assert "1200, 1300" in out

    node.stop()
    controller.terminate()


@pytest.mark.parametrize(
    "reset_reason,fault,expected",
    [
        (0, 0, "normal"),  # power-on
        (1 << 25, 0, "normal"),  # commanded stop
        (1 << 3, 0, "normal"),  # soft-reset
        (
            1 << 4,
            0,
            "normal",
        ),  # lockup: a cabled flash sets this on first boot
        (0, 3, "hung"),  # WatchdogTimeout: an app that finished, deliberately
        (1 << 1, 3, "hung"),  # the deadman fired, still no fault raised
        (1 << 1, 0, "crashed"),  # crash deadman with no fault latched
        (0, 1, "crashed"),  # HardFault
        (0, 2, "crashed"),  # SecureFault
    ],
)
def test_reset_severity_matches_the_wording_of_format_reset_cause(
    reset_reason, fault, expected
):
    """The tier and the sentence must not disagree.

    A UI styles by the tier and shows the sentence, so a bot reading "hung"
    beside a crash badge would be its own bug.
    """
    from swarmit.testbed.controller import (
        NodeStatus,
        format_reset_cause,
        reset_severity,
    )

    node = NodeStatus(reset_reason=reset_reason, fault=fault)

    assert reset_severity(node) == expected
    if expected != "normal":
        assert format_reset_cause(node).startswith(expected)


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch("swarmit.testbed.controller.COMMAND_MAX_ATTEMPTS", 3)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_stop_survives_a_device_pruned_mid_stop():
    """A device that goes silent mid-stop is retried, not a KeyError."""
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x01, status=StatusType.Running, adapter=test_adapter
    )
    test_adapter.add_node(node)
    time.sleep(0.3)
    addr = f"{node.address:08X}"
    assert addr in controller.running_devices
    node.enabled = False
    time.sleep(0.2)

    def prune(*_args, **_kwargs):
        controller.cleanup_inactive(0)

    with patch.object(
        controller, "send_payload", side_effect=prune
    ) as send_payload:
        controller.stop(devices=[addr])

    assert send_payload.call_count == 3
    controller.terminate()
