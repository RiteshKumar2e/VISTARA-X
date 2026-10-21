import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(Settings(detector_mode="simulated"))) as c:
        yield c


def wait_for(client, statuses, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get("/telemetry").json()["mission"]["status"]
        if s in statuses:
            return s
        time.sleep(0.1)
    raise AssertionError(f"status never reached {statuses}")


def test_health_and_status(client):
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["service"] == "vistara-x-backend"
    assert health["subsystems"]["simulation"]["ok"] is True
    assert health["subsystems"]["simulation"]["physics"] in ("pybullet", "analytic")
    status = client.get("/status").json()
    assert status["backend"] == "ok"
    assert status["simulation"]["running"] is True
    assert status["perception"]["mode"] == "simulated"
    assert status["perception"]["source_label"] == "Simulated (ground truth)"


def test_map_path_detections(client):
    m = client.get("/map").json()
    assert m["width"] == 20 and m["height"] == 12
    assert len(m["grid"]["blocked"]) == m["grid"]["rows"]
    assert client.get("/path").json()["path"] == []
    assert client.get("/detections").json()["mode"] == "simulated"
    assert client.get("/scenarios").json()["scenarios"][0]["key"] == "warehouse"


def test_validation_errors_are_structured(client):
    r = client.post("/target", json={"x": 50, "y": 3})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "x"
    assert client.post("/target", json={"x": "abc", "y": 1}).status_code == 422
    assert client.post("/target", json={"x": 1, "y": 1, "extra": 1}).status_code == 422
    assert client.post("/simulation/config", json={"max_speed": 9}).status_code == 422
    assert client.post("/perception/mode", json={"mode": "magic"}).status_code == 422
    r = client.post("/simulation/reset", json={"scenario": "nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_scenario"
    r = client.get("/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_conflicts(client):
    r = client.post("/navigate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_target"
    r = client.post("/target", json={"x": 5.0, "y": 9.5})
    assert r.status_code == 409 and r.json()["error"]["code"] == "target_unsafe"
    assert client.post("/navigation/pause").status_code == 409
    assert client.post("/navigation/resume").status_code == 409
    assert client.post("/navigation/stop").status_code == 409
    assert client.post("/obstacles/inject").status_code == 409


def test_full_mission_via_api(client):
    client.post("/simulation/config", json={"max_speed": 1.5})
    r = client.post("/navigate", json={"target": {"x": 18.5, "y": 6.0}})
    assert r.status_code == 200 and r.json()["ok"]
    wait_for(client, {"navigating"})
    assert len(client.get("/path").json()["path"]) >= 2
    time.sleep(1.5)
    r = client.post("/obstacles/inject")
    assert r.status_code == 201, r.text
    time.sleep(0.5)
    assert client.get("/telemetry").json()["mission"]["replans"] >= 1
    assert wait_for(client, {"goal_reached", "blocked"}, timeout=90) == "goal_reached"
    tel = client.get("/telemetry").json()
    assert tel["safety"]["collisions"] == 0
    assert tel["distance_to_target"] <= 0.2


def test_pause_resume_stop_reset_via_api(client):
    client.post("/target", json={"x": 18.5, "y": 6.0})
    client.post("/navigate")
    wait_for(client, {"navigating"})
    assert client.post("/navigation/pause").json()["status"] == "paused"
    x1 = client.get("/telemetry").json()["robot"]["x"]
    time.sleep(0.4)
    assert client.get("/telemetry").json()["robot"]["x"] == x1
    assert client.post("/navigation/resume").status_code == 200
    wait_for(client, {"navigating"})
    assert client.post("/navigation/stop").json()["status"] == "stopped"
    assert client.post("/simulation/reset", json={"scenario": "slalom"}).json()["status"] == "idle"
    assert client.get("/telemetry").json()["scenario"] == "slalom"


def test_obstacles_and_detector_mode(client):
    r = client.post("/obstacles", json={"x": 3, "y": 9, "shape": "circle", "size": 0.6})
    assert r.status_code == 201
    assert client.delete("/obstacles").json()["removed"] == 1
    assert client.post("/perception/mode", json={"mode": "simulated"}).status_code == 200


def test_perception_frame(client):
    for _ in range(30):
        r = client.get("/perception/frame")
        if r.status_code == 200:
            break
        time.sleep(0.1)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"


def test_cors_allows_dev_origin_only(client):
    ok = client.options(
        "/target",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        "/target",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_rate_limit(client):
    codes = [client.post("/navigation/stop").status_code for _ in range(35)]
    assert 429 in codes


def test_perception_controls(client):
    r = client.post("/perception/config", json={"rate_hz": 2, "confidence": 0.4})
    assert r.status_code == 200
    assert r.json()["rate_hz"] == 2 and r.json()["confidence_threshold"] == 0.4
    assert client.post("/perception/config", json={"confidence": 1.5}).status_code == 422
    assert client.post("/perception/config", json={"enabled": False}).json()["enabled"] is False
    d = client.get("/detections").json()
    assert d["enabled"] is False and d["detections"] == []
    client.post("/perception/config", json={"enabled": True})


def test_map_reports_unknown_cells(client):
    time.sleep(0.6)  # let the camera observe something
    grid = client.get("/map").json()["grid"]
    joined = "".join(grid["cells"])
    assert "#" in joined and "+" in joined and "?" in joined and "." in joined
    assert len(grid["cells"]) == grid["rows"] and len(grid["cells"][0]) == grid["cols"]


def test_telemetry_is_versioned_and_serialisable(client):
    import json

    snap = client.get("/telemetry").json()
    assert snap["version"] == 1
    assert json.loads(json.dumps(snap)) == snap
    for key in ("goal_reached", "progress", "replans"):
        assert key in snap["mission"]
    assert "tracks" in snap["perception"] and "explored" in snap["perception"]
    assert snap["perception"]["camera"] == {"fov_deg": 70.0, "height": 0.5, "range": 12.0, "forward_offset": 0.32}


def test_sensor_endpoints(client):
    time.sleep(0.5)
    data = client.get("/sensors").json()
    keys = {s["key"] for s in data["sensors"]}
    assert {"camera", "depth", "lidar", "ultrasonic", "imu", "odometry"} <= keys
    assert all(s["simulated"] for s in data["sensors"])
    assert data["proximity"]["action"] in ("clear", "slow", "stop", "degraded")
    r = client.post("/sensors/configure", json={"sensor": "lidar", "rate_hz": 5, "params": {"fov_deg": 180}})
    assert r.status_code == 200 and r.json()["sensor"]["config"]["fov_deg"] == 180
    assert client.post("/sensors/configure", json={"sensor": "lidar", "params": {"fov_deg": 5}}).status_code == 422
    assert client.post("/sensors/configure", json={"sensor": "sonar"}).status_code == 422
    r = client.post("/sensors/configure", json={"sensor": "ultrasonic", "enabled": False})
    assert r.json()["sensor"]["health"] == "disabled"
    assert "sensors" in client.get("/telemetry").json()


def test_model_endpoints(client):
    m = client.get("/models").json()
    assert m["models"][0]["key"] == "simulated"
    assert m["policy"]["mode"] in ("single", "cascade", "multi")
    assert client.post("/models/select", json={"primary": "nope"}).status_code == 422
    assert client.post("/models/select", json={"mode": "everything"}).status_code == 422
    r = client.post("/models/select", json={"primary": "simulated", "confidence": 0.4, "iou": 0.6})
    assert r.status_code == 200 and r.json()["policy"]["confidence"] == 0.4 and r.json()["policy"]["iou"] == 0.6


def test_simulation_obstacles_add_and_remove(client):
    r = client.post("/simulation/obstacles", json={"x": 3, "y": 9})
    assert r.status_code == 201
    oid = r.json()["obstacle"]["id"]
    assert client.delete(f"/simulation/obstacles/{oid}").json() == {"ok": True, "removed": oid}
    assert client.delete(f"/simulation/obstacles/{oid}").status_code == 404
    assert client.delete("/simulation/obstacles/shelf-1").status_code == 409


def test_mapping_endpoints(client, tmp_path):
    client.app.state.engine.maps_dir = tmp_path
    time.sleep(0.5)  # let a few LiDAR scans in
    m = client.get("/mapping").json()
    assert m["kind"] == "slam" and m["resolution"] == 0.1
    assert len(m["cells"]) == m["rows"] and set("".join(m["cells"])) <= set("ufo")
    assert m["status"]["source"] == "simulation" and m["status"]["scans"] > 0
    assert client.get("/mapping?which=imported").status_code == 404
    pgm = client.get("/mapping/export?file=pgm")
    assert pgm.status_code == 200 and pgm.content.startswith(b"P5")
    yaml = client.get("/mapping/export?file=yaml").text
    assert "resolution: 0.1" in yaml
    assert client.post("/mapping/save", json={"name": "demo"}).status_code == 200
    assert client.get("/mapping/maps").json()["maps"][0]["name"] == "demo"
    assert client.post("/mapping/save", json={"name": "../evil"}).status_code == 422
    loaded = client.post("/mapping/load", json={"name": "demo"}).json()["map"]
    assert loaded["resolution"] == 0.1
    assert client.post("/mapping/planner", json={"source": "imported"}).status_code == 200
    assert client.post("/mapping/planner", json={"source": "simulator"}).status_code == 200


def test_map_import_validation(client):
    import base64

    bad = client.post("/mapping/import", json={"name": "x", "yaml": "resolution: 0.05\norigin: [0, 0, 0]\n",
                                               "pgm_base64": base64.b64encode(b"P6 nope").decode()})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_map"
    pgm = b"P5\n4 2\n255\n" + bytes([254, 254, 0, 205, 254, 254, 254, 205])
    ok = client.post("/mapping/import", json={"name": "tiny", "yaml": "image: t.pgm\nresolution: 0.5\norigin: [0, 0, 0]\n",
                                              "pgm_base64": base64.b64encode(pgm).decode()})
    assert ok.status_code == 200
    m = client.get("/mapping?which=imported").json()
    # First image row is the top of the map: it becomes the last row in map order.
    assert m["cells"] == ["fffu", "ffou"]


def test_command_endpoints(client):
    places = client.get("/places").json()
    assert any(p["key"] == "reception" for p in places["places"])
    rec = client.post("/commands/interpret", json={"text": "Robot ko reception tak le jao"}).json()
    assert rec["status"] == "awaiting_confirmation" and rec["language"] == "hi-Latn"
    done = client.post(f"/commands/{rec['id']}/confirm").json()
    assert done["status"] == "executed"
    assert client.post(f"/commands/{rec['id']}/confirm").status_code == 409  # not pending any more
    wait_for(client, {"navigating"})
    stop = client.post("/commands/interpret", json={"text": "रुको", "source": "speech"}).json()
    assert stop["status"] == "executed"
    assert client.get("/telemetry").json()["mission"]["status"] == "stopped"
    hist = client.get("/commands").json()["commands"]
    assert [h["transcript"] for h in hist][-1] == "रुको"
    assert client.post("/commands/interpret", json={"text": "x" * 301}).status_code == 422


def test_speech_endpoint_validation(client):
    status = client.get("/speech/status").json()
    assert status["engine"].startswith("faster-whisper")
    r = client.post("/speech/transcribe", content=b"abc", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    r = client.post("/speech/transcribe?language=fr", content=b"abc", headers={"Content-Type": "audio/wav"})
    assert r.status_code == 422


def test_emergency_stop_always_succeeds(client):
    r = client.post("/navigation/estop")
    assert r.status_code == 200 and "not moving" in r.json()["message"]
    client.post("/target", json={"x": 18.5, "y": 6})
    client.post("/navigate")
    wait_for(client, {"navigating"})
    r = client.post("/navigation/estop").json()
    assert r["status"] == "stopped" and "halted" in r["message"]
