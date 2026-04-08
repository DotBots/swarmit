import base64
import datetime
import time

import pytest
from fastapi.testclient import TestClient

from swarmit.testbed.controller import ControllerSettings
from swarmit.testbed.protocol import StatusType
from swarmit.testbed.webserver import api, init_api, mount_frontend
from swarmit.tests.utils import (
    MarilibSerialAdapterMock,
    SwarmitNode,
)


def public_key_not_found():
    raise FileNotFoundError("public.pem not found")


@pytest.fixture
def client(monkeypatch, tmp_path, capsys):
    def fake_jwt_encode(*_args, **_kwargs):
        return "FAKE_TOKEN"

    def fake_jwt_decode(*_args, **_kwargs):
        return {"user": "ok"}

    monkeypatch.setattr("swarmit.testbed.controller.INACTIVE_TIMEOUT", 0.3)
    monkeypatch.setattr(
        "swarmit.testbed.controller.COMMAND_ATTEMPT_DELAY", 0.3
    )
    monkeypatch.setattr(
        "swarmit.testbed.webserver.jwt.encode", fake_jwt_encode
    )
    monkeypatch.setattr(
        "swarmit.testbed.webserver.jwt.decode", fake_jwt_decode
    )
    monkeypatch.setattr(
        "swarmit.testbed.adapter.MarilibSerialAdapter",
        MarilibSerialAdapterMock,
    )
    monkeypatch.setattr("swarmit.testbed.webserver.DATA_DIR", f"{tmp_path}")
    monkeypatch.setattr(
        "swarmit.testbed.webserver.API_DB_URL",
        f"sqlite:///{tmp_path}/database.db",
    )

    public_key_path = tmp_path / "public.pem"
    private_key_path = tmp_path / "private.pem"
    public_key_path.write_text("PUBLIC_KEY")
    private_key_path.write_text("PRIVATE_KEY")

    controller = init_api(
        api,
        ControllerSettings(
            network_id=999, adapter="edge", adapter_wait_timeout=0.1
        ),
    )
    mount_frontend(api)
    capsys.readouterr()

    with TestClient(api) as c:
        # lifespan has run: setup() was called, adapter is ready
        test_adapter = controller.interface.mari.serial_interface
        node1 = SwarmitNode(address=0x01, adapter=test_adapter)
        node2 = SwarmitNode(address=0x02, adapter=test_adapter)
        node3 = SwarmitNode(
            address=0x03, status=StatusType.Running, adapter=test_adapter
        )
        for node in [node1, node2, node3]:
            test_adapter.add_node(node)
        time.sleep(0.5)  # let status frames propagate through asyncio loop
        yield c

    # Reset OTA state between test runs
    api.state.ota_status = "idle"
    api.state.ota_error = None


# ------------------------------------------------------------------
# Status / settings
# ------------------------------------------------------------------


def test_status_endpoint(client):
    res = client.get("/status")
    assert res.status_code == 200
    assert "response" in res.json()


def test_settings_endpoint(client):
    res = client.get("/settings")
    assert res.status_code == 200
    assert res.json() == {
        "network_id": 999,
        "area_height": 2500,
        "area_width": 2500,
    }


# ------------------------------------------------------------------
# Start
# ------------------------------------------------------------------


def test_start_endpoint(client):
    res = client.post(
        "/start",
        json={"devices": "00000002"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_start_no_public_key(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    res = client.post(
        "/start",
        json={"devices": "00000002"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


def test_start_token_expired(client, monkeypatch):
    import jwt

    def token_expired(*_args, **_kwargs):
        raise jwt.ExpiredSignatureError("Token has expired")

    monkeypatch.setattr("swarmit.testbed.webserver.jwt.decode", token_expired)
    res = client.post(
        "/start",
        json={"devices": "00000002"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Token expired"


def test_start_token_invalid(client, monkeypatch):
    import jwt

    def token_invalid(*_args, **_kwargs):
        raise jwt.InvalidTokenError("Invalid token")

    monkeypatch.setattr("swarmit.testbed.webserver.jwt.decode", token_invalid)
    res = client.post(
        "/start",
        json={"devices": "00000002"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid token"


def test_start_devices_none(client):
    res = client.post(
        "/start",
        json={"devices": None},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_start_devices_not_string(client):
    res = client.post(
        "/start",
        json={"devices": 12345},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 422
    assert (
        res.json()["detail"][0]["msg"]
        == "Value error, devices must be a string or list of strings"
    )


def test_start_devices_not_list_of_strings(client):
    res = client.post(
        "/start",
        json={"devices": [123, "456"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 422
    assert (
        res.json()["detail"][0]["msg"]
        == "Value error, devices must be a list of strings"
    )


# ------------------------------------------------------------------
# Stop
# ------------------------------------------------------------------


def test_stop_endpoint(client):
    res = client.post(
        "/stop",
        json={"devices": ["00000003"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_stop_no_public_key(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    res = client.post(
        "/stop",
        json={"devices": "00000003"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


# ------------------------------------------------------------------
# OTA start
# ------------------------------------------------------------------


def test_ota_start_success(client):
    fw = base64.b64encode(b"hello" * 50).decode()
    res = client.post(
        "/ota/start",
        json={"firmware_b64": fw, "devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "00000001" in data["acked"]
    assert data["missed"] == []
    assert data["total_chunks"] > 0
    assert data["fw_hash"] != ""


def test_ota_start_no_public_key(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    fw = base64.b64encode(b"hello").decode()
    res = client.post(
        "/ota/start",
        json={"firmware_b64": fw, "devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


def test_ota_start_invalid_base64(client):
    res = client.post(
        "/ota/start",
        json={"firmware_b64": "***notbase64***"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 400
    assert "invalid firmware encoding" in res.json()["detail"]


def test_ota_start_no_ready_device(client):
    fw = base64.b64encode(b"abc").decode()
    res = client.post(
        "/ota/start",
        json={"firmware_b64": fw, "devices": ["00000003"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "no ready devices to flash"


def test_ota_start_missing_acks(client, monkeypatch):
    from swarmit.testbed.controller import StartOtaData

    async def fake_start_ota(_self, fw, devices=None):
        return {"ota": StartOtaData(), "missed": ["00000001"], "acked": []}

    monkeypatch.setattr(
        "swarmit.testbed.controller.Controller.start_ota", fake_start_ota
    )
    fw = base64.b64encode(b"abc").decode()
    res = client.post(
        "/ota/start",
        json={"firmware_b64": fw, "devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["missed"] == ["00000001"]
    assert data["acked"] == []


# ------------------------------------------------------------------
# OTA chunks + progress
# ------------------------------------------------------------------


def test_ota_full_success(client):
    fw = base64.b64encode(b"hello" * 50).decode()
    # Step 1: negotiate start
    res = client.post(
        "/ota/start",
        json={"firmware_b64": fw, "devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    acked = res.json()["acked"]

    # Step 2: transfer chunks (background task, completes before TestClient returns)
    res = client.post(
        "/ota/chunks",
        json={"devices": acked},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"status": "started"}

    # Step 3: check progress
    prog = client.get(
        "/ota/progress", headers={"Authorization": "Bearer FAKE_TOKEN"}
    )
    assert prog.status_code == 200
    data = prog.json()
    assert data["status"] == "success"
    assert data["error"] is None


def test_ota_chunks_already_running(client):
    client.app.state.ota_status = "running"
    res = client.post(
        "/ota/chunks",
        json={"devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 409
    assert "already in progress" in res.json()["detail"]
    client.app.state.ota_status = "idle"


def test_ota_chunks_no_public_key(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    res = client.post(
        "/ota/chunks",
        json={"devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


def test_ota_chunks_transfer_failed(client, monkeypatch):
    from swarmit.testbed.controller import StartOtaData, TransferDataStatus

    async def fake_start_ota(_self, fw, devices=None):
        return {"ota": StartOtaData(), "missed": [], "acked": ["00000001"]}

    async def fake_transfer(_self, devices):
        return {"00000001": TransferDataStatus(success=False)}

    monkeypatch.setattr(
        "swarmit.testbed.controller.Controller.start_ota", fake_start_ota
    )
    monkeypatch.setattr(
        "swarmit.testbed.controller.Controller.transfer", fake_transfer
    )

    fw = base64.b64encode(b"abc").decode()
    client.post(
        "/ota/start",
        json={"firmware_b64": fw, "devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    res = client.post(
        "/ota/chunks",
        json={"devices": ["00000001"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200

    prog = client.get(
        "/ota/progress", headers={"Authorization": "Bearer FAKE_TOKEN"}
    )
    assert prog.json()["status"] == "failed"
    assert prog.json()["error"] == "transfer failed"


def test_ota_progress_idle(client):
    client.app.state.ota_status = "idle"
    client.app.state.ota_error = None
    res = client.get(
        "/ota/progress", headers={"Authorization": "Bearer FAKE_TOKEN"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "idle"
    assert data["error"] is None
    assert data["total_chunks"] == 0


def test_ota_progress_failed(client):
    client.app.state.ota_status = "failed"
    client.app.state.ota_error = "transfer failed"
    res = client.get(
        "/ota/progress", headers={"Authorization": "Bearer FAKE_TOKEN"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert data["error"] == "transfer failed"


def test_ota_progress_requires_token(client):
    res = client.get("/ota/progress")
    assert res.status_code in (401, 403)


# ------------------------------------------------------------------
# Reset / message
# ------------------------------------------------------------------


def test_reset_endpoint(client):
    res = client.post(
        "/reset",
        json={"locations": {"00000001": {"pos_x": 100, "pos_y": 200}}},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_reset_invalid_location(client):
    res = client.post(
        "/reset",
        json={"locations": {"00000001": {"bad_key": 0}}},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 400
    assert "invalid location data" in res.json()["detail"]


def test_reset_no_public_key(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    res = client.post(
        "/reset",
        json={"locations": {"00000001": {"pos_x": 0, "pos_y": 0}}},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


def test_message_endpoint(client, capsys):
    res = client.post(
        "/message",
        json={"message": "hello swarm", "devices": ["00000003"]},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}
    assert "received message: hello swarm" in capsys.readouterr().out


def test_message_broadcast(client):
    res = client.post(
        "/message",
        json={"message": "broadcast", "devices": None},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_message_no_public_key(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    res = client.post(
        "/message",
        json={"message": "hello"},
        headers={"Authorization": "Bearer FAKE_TOKEN"},
    )
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


# ------------------------------------------------------------------
# JWT management
# ------------------------------------------------------------------


def test_issue_jwt(client):
    start_time = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=10)
    ).isoformat()
    res = client.post("/issue_jwt", json={"start": start_time})
    assert res.status_code == 200
    assert res.json()["data"] == "FAKE_TOKEN"

    res = client.get("/records")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_issue_same_jwt_twice(client):
    start_time = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=10)
    ).isoformat()
    client.post("/issue_jwt", json={"start": start_time})
    res = client.post("/issue_jwt", json={"start": start_time})
    assert res.status_code == 400
    assert res.json()["detail"] == "Timeslot already full"


def test_issue_jwt_no_private_key(client, monkeypatch):
    def private_key_not_found():
        raise FileNotFoundError("private.pem not found")

    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_private_key", private_key_not_found
    )
    res = client.post("/issue_jwt", json={"start": "2024-01-01T00:00:00Z"})
    assert res.status_code == 500
    assert "private.pem not found" in res.json()["detail"]


def test_issue_jwt_invalid_format(client):
    res = client.post("/issue_jwt", json={"start": "BAD_FORMAT"})
    assert res.status_code == 400
    assert "Invalid 'start' time format" in res.json()["detail"]


def test_public_key_success(client):
    res = client.get("/public_key")
    assert res.status_code == 200
    assert res.json()["data"] == "PUBLIC_KEY"


def test_public_key_not_found(client, monkeypatch):
    monkeypatch.setattr(
        "swarmit.testbed.webserver.get_public_key", public_key_not_found
    )
    res = client.get("/public_key")
    assert res.status_code == 500
    assert "public.pem not found" in res.json()["detail"]


def test_frontend_not_exists(client, capsys, monkeypatch):
    monkeypatch.setattr("os.path.isdir", lambda _path: False)
    mount_frontend(client.app)
    assert "Warning: dashboard directory not found" in capsys.readouterr().out
