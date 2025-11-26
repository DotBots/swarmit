import logging
import time
from unittest.mock import patch

from swarmit.testbed.controller import (
    Controller,
    ControllerSettings,
    ResetLocation,
)
from swarmit.testbed.logger import setup_logging
from swarmit.testbed.protocol import StatusType
from swarmit.tests.utils import SwarmitNode, SwarmitTestAdapter


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.INACTIVE_TIMEOUT", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
    time.sleep(0.15)
    assert sorted(controller.ready_devices) == [f"{nodes[1].address:08X}"]
    assert sorted(controller.running_devices) == [f"{nodes[0].address:08X}"]
    assert sorted(controller.resetting_devices) == []

    nodes[1].status = StatusType.Resetting
    time.sleep(0.15)
    assert sorted(controller.ready_devices) == []
    assert sorted(controller.resetting_devices) == [f"{nodes[1].address:08X}"]
    assert sorted(controller.running_devices) == [f"{nodes[0].address:08X}"]

    nodes[0].enabled = False
    time.sleep(1.2)

    assert list(controller.known_devices.keys()) == [f"{nodes[1].address:08X}"]

    controller.terminate()


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
    time.sleep(0.15)
    assert all([node.status == StatusType.Running for node in nodes]) is True


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
    time.sleep(0.15)
    assert nodes[0].status == StatusType.Running
    assert nodes[1].status == StatusType.Bootloader
    assert nodes[2].status == StatusType.Running


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
    time.sleep(0.15)
    assert (
        all([node.status == StatusType.Bootloader for node in nodes]) is True
    )


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
    time.sleep(0.15)
    assert nodes[0].status == StatusType.Bootloader
    assert nodes[1].status == StatusType.Running
    assert nodes[2].status == StatusType.Bootloader


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
        "00000001": ResetLocation(pos_x=1000000, pos_y=2000000),
        "00000002": ResetLocation(pos_x=2000000, pos_y=1000000),
    }
    controller.reset(locations=locations)
    time.sleep(0.15)
    for node in nodes:
        assert node.status == StatusType.Resetting
    controller.stop(timeout=0.1)
    time.sleep(0.15)
    assert (
        all([node.status == StatusType.Bootloader for node in nodes]) is True
    )


@patch("swarmit.testbed.controller.COMMAND_TIMEOUT", 0.1)
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
        "00000001": ResetLocation(pos_x=1000000, pos_y=2000000),
        "00000002": ResetLocation(pos_x=2000000, pos_y=1000000),
    }
    controller.reset(locations=locations)
    time.sleep(0.15)
    assert node1.status == StatusType.Resetting
    assert node2.status == StatusType.Running

    controller.stop(timeout=0.1)
    time.sleep(0.15)
    assert node1.status == StatusType.Bootloader
    assert node2.status == StatusType.Bootloader


@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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


@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
@patch("swarmit.testbed.adapter.MarilibSerialAdapter", SwarmitTestAdapter)
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
