import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(Settings(detector_mode="simulated"))) as c:
        yield c


def test_telemetry_stream(client):
    with client.websocket_connect("/ws/telemetry") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "telemetry"
        for key in ("robot", "mission", "path", "target", "perception", "events", "safety"):
            assert key in first
        client.post("/navigate", json={"target": {"x": 18.5, "y": 6.0}})
        seqs, statuses = [], set()
        for _ in range(15):
            msg = json.loads(ws.receive_text())
            seqs.append(msg["seq"])
            statuses.add(msg["mission"]["status"])
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # fresh and ordered
        assert "navigating" in statuses
        assert msg["target"] == {"x": 18.5, "y": 6.0}
        assert len(msg["path"]) >= 2


def test_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/telemetry", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()


def test_reconnect(client):
    for _ in range(3):
        with client.websocket_connect("/ws/telemetry") as ws:
            assert json.loads(ws.receive_text())["type"] == "telemetry"
    assert client.get("/status").json()["telemetry"]["clients"] == 0


def test_invalid_client_messages_get_errors(client):
    with client.websocket_connect("/ws/telemetry") as ws:
        json.loads(ws.receive_text())
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "ping"}))
        kinds = set()
        for _ in range(30):
            msg = json.loads(ws.receive_text())
            kinds.add(msg["type"])
            if {"error", "pong"} <= kinds:
                break
        assert {"error", "pong"} <= kinds
