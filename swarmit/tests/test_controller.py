import asyncio
import logging

import pytest
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


@pytest.fixture
async def edge_controller(monkeypatch):
    """Async fixture: edge controller with mock serial adapter."""
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    controller = Controller(ControllerSettings(adapter_wait_timeout=0.1))
    await controller.setup()
    yield controller
    await controller.terminate()


async def test_controller_basic(edge_controller, monkeypatch):
    monkeypatch.setattr("swarmit.testbed.controller.INACTIVE_TIMEOUT", 0.1)
    controller = edge_controller
    test_adapter = controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    await asyncio.sleep(0.5)
    assert sorted(controller.status_data.keys()) == [
        f"{node.address:08X}" for node in nodes
    ]
    assert sorted(controller.ready_devices) == [
        f"{node.address:08X}" for node in nodes
    ]
    assert sorted(controller.running_devices) == []
    assert sorted(controller.resetting_devices) == []

    nodes[0].status = StatusType.Running
    await asyncio.sleep(0.5)
    assert sorted(controller.ready_devices) == [f"{nodes[1].address:08X}"]
    assert sorted(controller.running_devices) == [f"{nodes[0].address:08X}"]
    assert sorted(controller.resetting_devices) == []

    nodes[1].status = StatusType.Resetting
    await asyncio.sleep(0.5)
    assert sorted(controller.ready_devices) == []
    assert sorted(controller.resetting_devices) == [f"{nodes[1].address:08X}"]
    assert sorted(controller.running_devices) == [f"{nodes[0].address:08X}"]

    nodes[0].enabled = False
    await asyncio.sleep(1.5)
    assert list(controller.status_data.keys()) == [f"{nodes[1].address:08X}"]


async def test_controller_start_broadcast(edge_controller, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    test_adapter = edge_controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    await asyncio.sleep(0.3)
    await edge_controller.start()
    await asyncio.sleep(0.3)
    assert all(node.status == StatusType.Running for node in nodes)


async def test_controller_start_unicast(edge_controller, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    test_adapter = edge_controller.interface.mari.serial_interface
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

    await asyncio.sleep(0.3)
    await edge_controller.start(devices=["00000001", "00000003"])
    await asyncio.sleep(0.3)
    assert nodes[0].status == StatusType.Running
    assert nodes[1].status == StatusType.Bootloader
    assert nodes[2].status == StatusType.Running


async def test_controller_start_broadcast_cloud_adapter(monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibMQTTAdapter", MarilibMQTTAdapterMock
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    controller = Controller(
        ControllerSettings(
            adapter="cloud", network_id=42, adapter_wait_timeout=0.1
        )
    )
    await controller.setup()
    try:
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

        await asyncio.sleep(0.3)
        await controller.start()
        await asyncio.sleep(0.3)
        assert all(node.status == StatusType.Running for node in nodes)
    finally:
        await controller.terminate()


async def test_controller_stop_broadcast(edge_controller, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    test_adapter = edge_controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(
            address=addr, status=StatusType.Running, adapter=test_adapter
        )
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    await asyncio.sleep(0.3)
    await edge_controller.stop()
    await asyncio.sleep(0.3)
    assert all(node.status == StatusType.Bootloader for node in nodes)


async def test_controller_stop_unicast(edge_controller, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    test_adapter = edge_controller.interface.mari.serial_interface
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

    await asyncio.sleep(0.3)
    await edge_controller.stop(devices=["00000001", "00000003"])
    await asyncio.sleep(0.3)
    assert nodes[0].status == StatusType.Bootloader
    assert nodes[1].status == StatusType.Running
    assert nodes[2].status == StatusType.Bootloader


async def test_controller_reset(monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    controller = Controller(
        ControllerSettings(
            devices=["00000001", "00000002"], adapter_wait_timeout=0.1
        )
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        nodes = [
            SwarmitNode(address=addr, adapter=test_adapter)
            for addr in [0x01, 0x02]
        ]
        for node in nodes:
            test_adapter.add_node(node)

        await asyncio.sleep(0.3)
        locations = {
            "00000001": ResetLocation(pos_x=1000000, pos_y=2000),
            "00000002": ResetLocation(pos_x=2000000, pos_y=1000),
        }
        await controller.reset(locations=locations)
        await asyncio.sleep(0.3)
        for node in nodes:
            assert node.status == StatusType.Resetting

        await controller.stop()
        await asyncio.sleep(0.3)
        assert all(node.status == StatusType.Bootloader for node in nodes)
    finally:
        await controller.terminate()


async def test_controller_reset_not_ready(monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1
    )
    controller = Controller(
        ControllerSettings(
            devices=["00000001", "00000002"], adapter_wait_timeout=0.1
        )
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        node1 = SwarmitNode(address=0x01, adapter=test_adapter)
        node2 = SwarmitNode(
            address=0x02, status=StatusType.Running, adapter=test_adapter
        )
        nodes = [node1, node2]
        for node in nodes:
            test_adapter.add_node(node)

        await asyncio.sleep(0.3)
        locations = {
            "00000001": ResetLocation(pos_x=1000000, pos_y=2000),
            "00000002": ResetLocation(pos_x=2000000, pos_y=1000),
        }
        await controller.reset(locations=locations)
        await asyncio.sleep(0.3)
        assert node1.status == StatusType.Resetting
        assert node2.status == StatusType.Running

        await controller.stop()
        await asyncio.sleep(0.3)
        assert node1.status == StatusType.Bootloader
        assert node2.status == StatusType.Bootloader
    finally:
        await controller.terminate()


async def test_controller_log_events(edge_controller, caplog):
    """Verify log events from nodes are processed and filtered correctly."""
    caplog.set_level(logging.INFO)
    setup_logging()

    test_adapter = edge_controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)
        node.start_log_event_task()

    await asyncio.sleep(0.5)
    assert "LOG event" in caplog.text


async def test_controller_log_events_single_device(monkeypatch, caplog):
    """Verify log events are filtered to the configured device list."""
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    caplog.set_level(logging.INFO)
    setup_logging()

    controller = Controller(
        ControllerSettings(devices=["00000001"], adapter_wait_timeout=0.1)
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        nodes = [
            SwarmitNode(address=addr, adapter=test_adapter)
            for addr in [0x01, 0x02]
        ]
        for node in nodes:
            test_adapter.add_node(node)
            node.start_log_event_task()

        await asyncio.sleep(0.5)
        assert "00000001" in caplog.text
        assert "00000002" not in caplog.text
    finally:
        await controller.terminate()


async def test_controller_send_message_unicast(monkeypatch, capsys):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    controller = Controller(
        ControllerSettings(
            devices=["00000001", "00000003"], adapter_wait_timeout=0.1
        )
    )
    await controller.setup()
    try:
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

        await asyncio.sleep(0.3)
        await controller.send_message("Hello robot!")
        out, _ = capsys.readouterr()
        assert "Node 00000001 received message: Hello robot!" in out
        assert "Node 00000003 received message: Hello robot!" not in out
    finally:
        await controller.terminate()


async def test_controller_send_message_broadcast(edge_controller, capsys):
    test_adapter = edge_controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(
            address=addr, status=StatusType.Running, adapter=test_adapter
        )
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    await asyncio.sleep(0.3)
    await edge_controller.send_message("Hello robot!")
    out, _ = capsys.readouterr()
    for node in ["00000001", "00000002"]:
        assert f"Node {node} received message: Hello robot!" in out


async def test_controller_ota_broadcast(edge_controller, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1
    )
    test_adapter = edge_controller.interface.mari.serial_interface
    nodes = [
        SwarmitNode(address=addr, adapter=test_adapter)
        for addr in [0x01, 0x02]
    ]
    for node in nodes:
        test_adapter.add_node(node)

    await asyncio.sleep(0.3)
    firmware = b"\x00" * 2**16

    ota_data = await edge_controller.start_ota(firmware)
    assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]
    assert ota_data["missed"] == []
    for node in nodes:
        assert node.status == StatusType.Programming

    result = await edge_controller.transfer(ota_data["acked"])
    await asyncio.sleep(0.3)
    assert all(t.success for t in result.values())


async def test_controller_ota_broadcast_verbose(monkeypatch, capsys):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1
    )
    controller = Controller(
        ControllerSettings(adapter_wait_timeout=0.1, verbose=True)
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        nodes = [
            SwarmitNode(address=addr, adapter=test_adapter)
            for addr in [0x01, 0x02]
        ]
        for node in nodes:
            test_adapter.add_node(node)

        await asyncio.sleep(0.3)
        firmware = b"\x00" * 2**16

        ota_data = await controller.start_ota(firmware)
        assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]
        assert ota_data["missed"] == []

        result = await controller.transfer(ota_data["acked"])
        await asyncio.sleep(0.3)
        assert all(t.success for t in result.values())
        assert "Transfer completed" in capsys.readouterr().out
    finally:
        await controller.terminate()


async def test_controller_ota_unicast(monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1
    )
    controller = Controller(
        ControllerSettings(devices=["00000001"], adapter_wait_timeout=0.1)
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        nodes = [
            SwarmitNode(address=addr, adapter=test_adapter)
            for addr in [0x01, 0x02]
        ]
        for node in nodes:
            test_adapter.add_node(node)

        await asyncio.sleep(0.3)
        firmware = b"\x00" * 2**16 + b"\x01" * 1234

        ota_data = await controller.start_ota(firmware)
        assert ota_data["acked"] == ["00000001"]
        assert ota_data["missed"] == []
        assert nodes[0].status == StatusType.Programming
        assert nodes[1].status == StatusType.Bootloader

        result = await controller.transfer(ota_data["acked"])
        await asyncio.sleep(0.3)
        assert all(t.success for t in result.values())
    finally:
        await controller.terminate()


async def test_controller_ota_with_retries(monkeypatch, capsys):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1
    )
    controller = Controller(
        ControllerSettings(
            adapter_wait_timeout=0.1, ota_max_retries=3, verbose=True
        )
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        node1 = SwarmitNode(
            address=0x01,
            ack_strategy=ChunkAckStrategy(
                ack_miss_index=5, ack_miss_retries=2
            ),
            adapter=test_adapter,
        )
        node2 = SwarmitNode(
            address=0x02,
            ack_strategy=ChunkAckStrategy(
                ack_miss_index=5, ack_miss_retries=4
            ),
            ota_should_fail=True,
            adapter=test_adapter,
        )
        nodes = [node1, node2]
        for node in nodes:
            test_adapter.add_node(node)

        await asyncio.sleep(0.3)
        firmware = b"\x00" * 2**16

        ota_data = await controller.start_ota(firmware)
        assert ota_data["acked"] == [f"{node.address:08X}" for node in nodes]
        assert ota_data["missed"] == []
        for node in nodes:
            assert node.status == StatusType.Programming

        result = await controller.transfer(ota_data["acked"])
        assert "Transfer completed with" in capsys.readouterr().out
        assert result["00000001"].success is True
        assert result["00000002"].success is False
        assert sum(c.retries for c in result["00000001"].chunks) == 2
        assert sum(c.retries for c in result["00000002"].chunks) == 3
    finally:
        await controller.terminate()


async def test_controller_ota_index_out_range(monkeypatch, capsys):
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.OTA_ACK_TIMEOUT_DEFAULT", 0.1
    )
    controller = Controller(
        ControllerSettings(
            adapter_wait_timeout=0.1, ota_max_retries=3, verbose=True
        )
    )
    await controller.setup()
    try:
        test_adapter = controller.interface.mari.serial_interface
        node = SwarmitNode(
            address=0x01,
            ack_strategy=ChunkAckStrategy(ack_out_of_range_index=50),
            ota_should_fail=True,
            adapter=test_adapter,
        )
        test_adapter.add_node(node)

        await asyncio.sleep(0.3)
        firmware = b"\x00" * 2**16

        ota_data = await controller.start_ota(firmware)
        assert ota_data["acked"] == [f"{node.address:08X}"]
        assert ota_data["missed"] == []
        assert node.status == StatusType.Programming

        result = await controller.transfer(ota_data["acked"])
        assert "Transfer completed with" in capsys.readouterr().out
        assert result["00000001"].success is False
        assert sum(c.retries for c in result["00000001"].chunks) == 3
    finally:
        await controller.terminate()


def test_controller_chunk_repr():
    chunk = Chunk(index=42, size=128, acked=True, retries=2)
    assert (
        repr(chunk)
        == "{'index': 42, 'size': 128, 'acked': True, 'retries': 2}"
    )
