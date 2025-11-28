import base64
import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from swarmit.testbed.controller import ControllerSettings
from swarmit.testbed.model import JWTRecord
from swarmit.testbed.webserver import (
    api,
    init_api,
)


@pytest.fixture
def controller_mock():
    """Mock the Controller so no hardware is touched."""

    class ControllerMock:
        def __init__(self, settings):
            self.settings = settings
            self.ready_devices_called = False
            self.start_called = False
            self.stop_called = False
            self.status_data = {}

        def ready_devices(self):
            self.ready_devices_called = True
            return []

        def start_ota(self, fw, devices=None):
            return {"acked": ["dev1"], "missed": []}

        def transfer(self, fw, acked):
            return {"dev1": MagicMock(success=True)}

        def start(self, devices=None):
            self.start_called = True

        def stop(self, devices=None):
            self.stop_called = True

    return ControllerMock


@pytest.fixture
def test_api(controller_mock):
    """Attach a mock Controller to the FastAPI lifespan."""
    with patch("swarmit.testbed.webserver.Controller", new=controller_mock):
        init_api(api, ControllerSettings(network_id=999))
        api.state.controller = controller_mock(
            settings=ControllerSettings(network_id=999)
        )
        client = TestClient(api)
        yield client


@pytest.fixture
def db_session_mock():
    class QueryMock:
        def __init__(self, parent):
            self.parent = parent
            self._records = parent.records

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return self._records

    class DBSessionMock:
        def __init__(self):
            self.records = []

        def add(self, obj):
            self.records.append(obj)

        def commit(self):
            pass

        def refresh(self, obj):
            pass

        def query(self, model):
            return QueryMock(self)

    return DBSessionMock()


@pytest.fixture
def valid_jwt_token():
    yield {"some": "payload"}


@pytest.fixture
def jwt_decode_mock():
    """Patch jwt.decode globally for endpoints requiring authentication."""
    with patch("swarmit.testbed.webserver.jwt.decode") as mock:
        mock.return_value = {"user": "ok"}
        yield mock


@pytest.fixture
def private_key_mock():
    """Mock loading of private key for /issue_jwt."""
    with patch(
        "swarmit.testbed.webserver.get_private_key", return_value="PRIVATE_KEY"
    ):
        yield


def test_status_endpoint(test_api):
    res = test_api.get("/status")
    assert res.status_code == 200
    assert "response" in res.json()


def test_settings_endpoint(test_api):
    res = test_api.get("/settings")
    assert res.status_code == 200
    assert res.json() == {"network_id": 999}


def test_start_endpoint(test_api, jwt_decode_mock, valid_jwt_token):
    res = test_api.post(
        "/start",
        json={"devices": "dev1"},
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_stop_endpoint(test_api, jwt_decode_mock, valid_jwt_token):
    res = test_api.post(
        "/stop",
        json={"devices": ["dev1"]},
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "done"}


def test_flash_firmware_success(test_api, jwt_decode_mock, valid_jwt_token):
    fw = base64.b64encode(b"hello").decode()
    res = test_api.post(
        "/flash",
        json={"firmware_b64": fw, "devices": ["dev1"]},
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )
    assert res.status_code == 200
    assert res.json() == {"response": "success"}


def test_flash_firmware_invalid_base64(
    test_api, jwt_decode_mock, valid_jwt_token
):
    res = test_api.post(
        "/flash",
        json={"firmware_b64": "***notbase64***"},
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )
    assert res.status_code == 400
    assert "invalid firmware encoding" in res.json()["detail"]


def test_flash_when_ready_devices_not_empty(
    test_api, jwt_decode_mock, valid_jwt_token
):
    instance = api.state.controller
    instance.ready_devices = lambda: ["dev1"]

    fw = base64.b64encode(b"abc").decode()
    res = test_api.post(
        "/flash",
        json={"firmware_b64": fw},
        headers={"Authorization": f"Bearer {valid_jwt_token}"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "no ready devices to flash"


def test_issue_jwt_success(test_api, db_session_mock, private_key_mock):
    from swarmit.testbed.webserver import get_db

    api.dependency_overrides[get_db] = lambda: db_session_mock

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with patch(
        "swarmit.testbed.webserver.jwt.encode", return_value="FAKE_TOKEN"
    ):
        res = test_api.post("/issue_jwt", json={"start": now})

    assert res.status_code == 200
    assert res.json()["data"] == "FAKE_TOKEN"  # <-- FIXED

    api.dependency_overrides.clear()


def test_issue_jwt_invalid_format(test_api):
    res = test_api.post("/issue_jwt", json={"start": "BAD_FORMAT"})
    assert res.status_code == 400
    assert "Invalid 'start' time format" in res.json()["detail"]


def test_public_key_success(test_api):
    res = test_api.get("/public_key")
    assert res.status_code == 200
    assert "data" in res.json()


def test_public_key_missing_file(test_api):
    with patch(
        "swarmit.testbed.webserver.get_public_key",
        side_effect=FileNotFoundError,
    ):
        res = test_api.get("/public_key")
        assert res.status_code == 500
        assert "public.pem not found" in res.json()["detail"]


def test_records_endpoint(test_api, db_session_mock):
    from swarmit.testbed.webserver import get_db

    api.dependency_overrides[get_db] = lambda: db_session_mock

    record = JWTRecord(
        jwt="token",
        date_start=datetime.datetime.now(datetime.timezone.utc),
        date_end=datetime.datetime.now(datetime.timezone.utc),
    )

    db_session_mock.records.append(record)

    res = test_api.get("/records")

    assert res.status_code == 200
    assert len(res.json()) == 1

    api.dependency_overrides.clear()
