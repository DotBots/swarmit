from unittest.mock import patch

from dotbot_utils.protocol import Packet
from marilib.mari_protocol import Frame as MariFrame
from marilib.mari_protocol import Header as MariHeader
from marilib.model import EdgeEvent

from swarmit.testbed.adapter import MarilibCloudAdapter, MarilibEdgeAdapter
from swarmit.testbed.protocol import PayloadStatus


@patch("swarmit.testbed.adapter.MarilibSerialAdapter")
@patch("swarmit.testbed.adapter.MarilibEdge.send_frame")
def test_marilib_edge_adapter(send_frame_mock, _, capsys):
    adapter = MarilibEdgeAdapter(
        port="p", baudrate=1, verbose=True, busy_wait_timeout=0.1
    )
    packets = []

    def on_frame_received(_, f):
        packets.append(f)

    payload = PayloadStatus(device=1, status=2)
    packet = Packet().from_payload(payload)
    mari_frame = MariFrame(header=MariHeader(), payload=packet.to_bytes())

    # should ignore if not initialized
    adapter.on_event(EdgeEvent.NODE_DATA, mari_frame)
    assert not packets

    adapter.init(on_frame_received)
    out, _ = capsys.readouterr()
    assert "Mari nodes available" in out

    adapter.on_event(EdgeEvent.NODE_DATA, mari_frame)

    assert packets == [packet]

    adapter.on_event(EdgeEvent.NODE_JOINED, None)
    out, _ = capsys.readouterr()
    assert "Node joined" in out

    adapter.on_event(EdgeEvent.NODE_LEFT, None)
    out, _ = capsys.readouterr()
    assert "Node left" in out

    # invalid frame
    mari_frame = MariFrame(header=MariHeader(), payload=b"`\x01invalid")
    adapter.on_event(EdgeEvent.NODE_DATA, mari_frame)
    out, _ = capsys.readouterr()
    assert "Error parsing packet" in out

    adapter.send_payload(mari_frame.header.destination, payload)
    send_frame_mock.assert_called_once_with(
        dst=mari_frame.header.destination, payload=packet.to_bytes()
    )
    adapter.close()


@patch("swarmit.testbed.adapter.MarilibSerialAdapter")
def test_marilib_edge_adapter_init_failed(serial_adapter_mock, capsys):
    serial_adapter_mock.side_effect = Exception("init failed")
    with patch("sys.exit") as exit_mock:
        MarilibEdgeAdapter(
            port="p", baudrate=1, verbose=True, busy_wait_timeout=0.1
        )

    exit_mock.assert_called_with(1)
    out, _ = capsys.readouterr()
    assert "Error initializing MarilibEdge" in out


@patch("swarmit.testbed.adapter.MarilibMQTTAdapter")
@patch("swarmit.testbed.adapter.MarilibCloud.send_frame")
def test_marilib_cloud_adapter(send_frame_mock, _, capsys):
    adapter = MarilibCloudAdapter(
        host="h",
        port=1,
        use_tls=False,
        network_id=2,
        verbose=True,
        busy_wait_timeout=0.1,
    )

    packets = []

    def on_frame_received(_, f):
        packets.append(f)

    payload = PayloadStatus(device=1, status=2)
    packet = Packet().from_payload(payload)
    mari_frame = MariFrame(header=MariHeader(), payload=packet.to_bytes())

    # should ignore if not initialized
    adapter.on_event(EdgeEvent.NODE_DATA, mari_frame)
    assert not packets

    adapter.init(on_frame_received)
    out, _ = capsys.readouterr()
    assert "Mari nodes available" in out

    adapter.on_event(EdgeEvent.NODE_DATA, mari_frame)

    assert packets == [packet]

    adapter.on_event(EdgeEvent.NODE_JOINED, None)
    out, _ = capsys.readouterr()
    assert "Node joined" in out

    adapter.on_event(EdgeEvent.NODE_LEFT, None)
    out, _ = capsys.readouterr()
    assert "Node left" in out

    # invalid frame
    mari_frame = MariFrame(header=MariHeader(), payload=b"`\x01invalid")
    adapter.on_event(EdgeEvent.NODE_DATA, mari_frame)
    out, _ = capsys.readouterr()
    assert "Error parsing packet" in out

    adapter.send_payload(mari_frame.header.destination, payload)
    send_frame_mock.assert_called_once_with(
        dst=mari_frame.header.destination, payload=packet.to_bytes()
    )
    adapter.close()


@patch("swarmit.testbed.adapter.MarilibMQTTAdapter")
def test_marilib_cloud_adapter_init_failed(mqtt_adapter_mock, capsys):
    mqtt_adapter_mock.side_effect = Exception("init failed")
    with patch("sys.exit") as exit_mock:
        MarilibCloudAdapter(
            host="h",
            port=1,
            use_tls=False,
            network_id=2,
            verbose=True,
            busy_wait_timeout=0.1,
        )

    exit_mock.assert_called_with(1)
    out, _ = capsys.readouterr()
    assert "Error initializing MarilibCloud" in out
