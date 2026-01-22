import logging
import time
from unittest.mock import patch

from marilib.model import GatewayInfo, MariGateway

from swarmit.testbed.controller import (
    Chunk,
    Controller,
    ControllerSettings,
    ResetLocation,
)
from swarmit.testbed.logger import setup_logging
from swarmit.testbed.protocol import StatusType
from swarmit.tests.utils import (
    ChunkAckStrategy,
    MarilibMQTTAdapterMock,
    MarilibSerialAdapterMock,
    SwarmitNode,
)


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

    controller.start(timeout=0.1)
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

    controller.start(devices=["00000001", "00000003"], timeout=0.1)
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

    controller.start(timeout=0.1)
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

    controller.stop(timeout=0.1)
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

    controller.stop(devices=["00000001", "00000003"], timeout=0.1)
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

    node1 = SwarmitNode(address=0x01, adapter=test_adapter)
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
    assert f"{2500/1000:.2f}V" in out
    assert f"{2100/1000:.2f}V" in out
    assert f"{1500/1000:.2f}V" in out


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibMQTTAdapter",
    MarilibMQTTAdapterMock,
)
def test_controller_status_adpater_cloud(capsys):
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
    controller.stop(timeout=0.1)
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

    controller.stop(timeout=0.1)
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


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
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
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_broadcast_verbose(capsys):
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
    assert "Transfer completed" in capsys.readouterr().out


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
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


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_with_retries(capsys):
    controller = Controller(
        ControllerSettings(
            adapter_wait_timeout=0.1, ota_max_retries=3, verbose=True
        )
    )
    test_adapter = controller.interface.mari.serial_interface
    node1 = SwarmitNode(
        address=0x01,
        ack_strategy=ChunkAckStrategy(ack_miss_index=5, ack_miss_retries=2),
        adapter=test_adapter,
    )
    node2 = SwarmitNode(
        address=0x02,
        ack_strategy=ChunkAckStrategy(ack_miss_index=5, ack_miss_retries=4),
        ota_should_fail=True,
        adapter=test_adapter,
    )
    nodes = [node1, node2]
    for node in nodes:
        test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]
    assert ota_data["missed"] == []

    for node in nodes:
        assert node.status == StatusType.Programming

    result = controller.transfer(firmware, ota_data["acked"])
    assert "Transfer completed with" in capsys.readouterr().out
    assert result["00000001"].success is True
    assert result["00000002"].success is False
    # retries are equal for both nodes (broadcast)
    assert sum(chunk.retries for chunk in result["00000001"].chunks) == 3
    assert sum(chunk.retries for chunk in result["00000002"].chunks) == 3


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1)
@patch(
    "swarmit.testbed.adapter.MarilibSerialAdapter", MarilibSerialAdapterMock
)
def test_controller_ota_index_out_range(capsys):
    controller = Controller(
        ControllerSettings(
            adapter_wait_timeout=0.1, ota_max_retries=3, verbose=True
        )
    )
    test_adapter = controller.interface.mari.serial_interface
    node = SwarmitNode(
        address=0x01,
        ack_strategy=ChunkAckStrategy(ack_out_of_range_index=50),
        ota_should_fail=True,
        adapter=test_adapter,
    )
    test_adapter.add_node(node)

    firmware = b"\x00" * 2**16

    ota_data = controller.start_ota(firmware)
    assert ota_data["acked"] == [f"{node.address:08X}"]
    assert ota_data["missed"] == []
    assert node.status == StatusType.Programming

    result = controller.transfer(firmware, ota_data["acked"])
    assert "Transfer completed with" in capsys.readouterr().out
    assert result["00000001"].success is False
    assert sum(chunk.retries for chunk in result["00000001"].chunks) == 3


def test_controller_chunk_repr():
    chunk = Chunk(index=42, size=128, acked=True, retries=2)
    assert (
        repr(chunk)
        == "{'index': 42, 'size': 128, 'acked': True, 'retries': 2}"
    )
