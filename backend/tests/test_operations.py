import math

import pytest
from fastapi.testclient import TestClient

from app.commands.service import CommandService
from app.config import Settings
from app.main import create_app
from app.operations.manager import CRITICAL, OpsError

MAX_STEPS = 4000  # 200 s of simulation


def _run(engine, until, steps=MAX_STEPS):
    for _ in range(steps):
        engine.step()
        if until():
            return True
    return False


@pytest.fixture
def hospital(engine):
    engine.reset("hospital")
    return engine


def test_full_delivery_with_load_pin_and_proof(hospital, tmp_path):
    ops = hospital.operations
    task = ops.create_task("pharmacy", "ward_b", "insulin", "normal", "Nurse Asha", "Ward B")
    assert len(task["pin"]) == 4 and task["status"] == "queued"
    assert _run(hospital, lambda: ops.tasks[0]["status"] == "loading")
    ops.confirm_loaded(task["id"], by="pharmacist")
    assert _run(hospital, lambda: ops.tasks[0]["status"] == "awaiting_pin")
    with pytest.raises(OpsError) as err:
        ops.deliver(task["id"], "0000" if task["pin"] != "0000" else "1111")
    assert err.value.code == "wrong_pin"
    done = ops.deliver(task["id"], task["pin"])
    assert done["status"] == "delivered" and "pin" not in done
    assert done["proof"]["method"] == "recipient PIN" and done["distance_m"] > 5
    assert [s["status"] for s in done["timeline"]] == ["queued", "to_pickup", "loading", "to_dropoff", "awaiting_pin", "delivered"]
    assert hospital.collisions == 0
    rep = ops.report()
    assert rep["delivered"] == 1 and rep["collisions"] == 0
    assert "insulin" in ops.report_csv()
    assert (ops.dir / "deliveries.jsonl").is_file()
    assert any("PIN verified" in n["text"] for n in ops.notifications)


def test_urgent_tasks_go_first_and_validation(hospital):
    ops = hospital.operations
    ops.auto_dispatch = False
    ops.create_task("lab", "reception", "report", "low")
    urgent = ops.create_task("pharmacy", "icu", "blood", "urgent")
    assert ops.snapshot()["queue"][0]["id"] == urgent["id"]
    with pytest.raises(OpsError):
        ops.create_task("pharmacy", "pharmacy")
    with pytest.raises(OpsError):
        ops.create_task("pharmacy", "cafeteria")


def test_cancel_active_task_stops_the_robot(hospital):
    ops = hospital.operations
    t = ops.create_task("ward_b", "reception", "files")
    assert _run(hospital, lambda: hospital.status == "navigating")
    ops.cancel(t["id"])
    assert ops.tasks[0]["status"] == "cancelled" and hospital.status == "stopped"


def test_low_battery_returns_to_dock_charges_and_resumes(hospital):
    ops = hospital.operations
    ops.configure(auto_load=True, battery=25)
    ops.create_task("reception", "pharmacy", "files")
    assert _run(hospital, lambda: ops.mode == "charging")
    dock = next(p for p in hospital.scenario.places if p.key == "charging")
    r = hospital.world.robot
    assert math.hypot(r.x - dock.x, r.y - dock.y) < 0.4
    assert _run(hospital, lambda: ops.tasks[0]["status"] == "awaiting_pin")
    assert ops.charge_cycles == 1 and ops.battery > 80


def test_critical_battery_requeues_a_pickup_leg(hospital):
    ops = hospital.operations
    ops.create_task("ward_b", "reception", "files")
    assert _run(hospital, lambda: ops.tasks[0]["status"] == "to_pickup")
    ops.battery = CRITICAL - 1
    hospital.step()
    assert ops.tasks[0]["status"] == "queued"


def test_emergency_stop_pauses_the_queue(hospital):
    ops = hospital.operations
    ops.create_task("ward_b", "reception", "files")
    assert _run(hospital, lambda: hospital.status == "navigating")
    hospital.emergency_stop()
    assert ops.auto_dispatch is False
    for _ in range(40):
        hospital.step()
    assert hospital.status == "stopped"  # nothing restarted the robot


def test_doors_open_for_the_robot_and_close_again(hospital):
    door = next(o for o in hospital.world.obstacles if o.id == "door-s1")
    closed_x = door.x
    hospital.set_target(4.0, 2.6)  # pharmacy, through door-s1
    hospital.navigate()
    assert _run(hospital, lambda: hospital.status == "goal_reached")
    assert hospital.collisions == 0
    assert any(e["message"] == "Door door-s1 open" for e in hospital.events)
    hospital.set_target(19.0, 6.0)
    hospital.navigate()
    assert _run(hospital, lambda: hospital.status == "goal_reached")
    assert _run(hospital, lambda: abs(door.x - closed_x) < 1e-6, steps=400)


def test_quiet_zone_limits_speed(hospital):
    hospital.set_target(16.0, 9.2)  # Ward B, inside the 0.4 m/s quiet zone
    hospital.navigate()
    fastest_inside = 0.0
    for _ in range(MAX_STEPS):
        hospital.step()
        r = hospital.world.robot
        if any(z.contains(r.x, r.y) for z in hospital.scenario.zones if z.key == "wards"):
            fastest_inside = max(fastest_inside, r.v)
        if hospital.status == "goal_reached":
            break
    assert hospital.status == "goal_reached"
    assert 0 < fastest_inside <= 0.4 + 1e-6
    assert any(e["type"] == "zone" for e in hospital.events)


def test_spoken_delivery_request_creates_a_task(hospital):
    hospital.operations.auto_dispatch = False
    svc = CommandService(hospital)
    rec = svc.interpret("Pharmacy se Ward B tak dawai le jao")
    assert rec["intent"]["type"] == "deliver" and rec["status"] == "awaiting_confirmation"
    assert rec["intent"]["pickup"]["key"] == "pharmacy" and rec["intent"]["destination"]["key"] == "ward_b"
    rec = svc.confirm(rec["id"])
    assert rec["status"] == "executed" and "PIN" in rec["response"]["text"]
    t = hospital.operations.tasks[0]
    assert t["item"] == "dawai" and t["pickup"]["key"] == "pharmacy"


def test_access_keys_roles_and_audit(tmp_path):
    cfg = Settings(detector_mode="simulated", ops_dir=str(tmp_path), operator_key="op-key", admin_key="admin-key")
    with TestClient(create_app(cfg)) as c:
        assert c.get("/auth/status").json() == {"enabled": True, "role": "viewer"}
        assert c.get("/operations").status_code == 200  # viewing is open
        assert c.post("/target", json={"x": 18.5, "y": 6}).status_code == 401
        assert c.post("/navigation/estop").status_code == 200  # never needs a key
        op = {"X-API-Key": "op-key"}
        assert c.post("/target", json={"x": 18.5, "y": 6}, headers=op).status_code == 200
        assert c.post("/simulation/reset", json={"scenario": "hospital"}, headers=op).status_code == 403
        admin = {"X-API-Key": "admin-key"}
        assert c.post("/simulation/reset", json={"scenario": "hospital"}, headers=admin).status_code == 200
        r = c.post("/operations/tasks", json={"pickup": "pharmacy", "dropoff": "icu", "item": "x"}, headers=op)
        assert r.status_code == 201 and len(r.json()["task"]["pin"]) == 4
        assert c.get("/audit", headers=op).status_code == 403
        entries = c.get("/audit", headers=admin).json()["entries"]
        assert entries[0]["path"] == "/operations/tasks" and entries[0]["role"] == "operator"
        assert any(e["status"] == 401 for e in entries)
        assert c.get("/operations/report.csv").text.startswith("id,scenario")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(detector_mode="simulated", ops_dir=str(tmp_path)))) as c:
        yield c


def test_operations_api_without_keys(client):
    r = client.post("/operations/tasks", json={"pickup": "reception", "dropoff": "exit", "item": "box"})
    assert r.status_code == 201
    tid = r.json()["task"]["id"]
    assert client.post(f"/operations/tasks/{tid}/deliver", json={"pin": "12a4"}).status_code == 422
    assert client.post(f"/operations/tasks/{tid}/deliver", json={"pin": "1234"}).status_code == 409  # not arrived
    assert client.get("/operations").json()["battery"]["level"] <= 100
