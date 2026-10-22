"""Delivery operations on top of the navigation engine.

A delivery task has a pickup and a drop-off place. The robot drives to the pickup and
waits until someone confirms the item is loaded, then drives to the drop-off and waits
for the recipient to enter the task's 4-digit PIN (proof of delivery). Tasks wait in a
queue ordered by priority (urgent, normal, low), then by request time.

Battery: the level drops with distance driven and with time, and rises at the charging
dock. Below LOW the robot finishes nothing new and returns to the dock; below CRITICAL
it abandons a pickup leg (the task is re-queued) but finishes a drop-off it has started,
because it is carrying the item. The rates are accelerated so a demo shows a full cycle
in minutes; they are not measured from a real battery.

The manager is ticked by the engine at the end of every simulation step, inside the
engine lock, and only starts missions when the engine is idle - a mission the operator
starts by hand always takes precedence.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import secrets
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("vistara.operations")

PRIORITIES = {"urgent": 0, "normal": 1, "low": 2}
DRAIN_PER_M = 0.4  # % per metre driven (demo-accelerated)
DRAIN_PER_S = 0.01  # % per second, electronics and sensors (demo-accelerated)
CHARGE_PER_S = 2.0  # % per second at the dock (demo-accelerated)
LOW = 30.0  # % : return to the dock after the current task
CRITICAL = 15.0  # % : return now unless carrying an item
RESUME = 95.0  # % : leave the dock again
DOCK_RADIUS = 0.35  # m
AUTO_LOAD_AFTER = 3.0  # s at the pickup when auto-load is on (demo)
MAX_ATTEMPTS = 2
MAX_PIN_TRIES = 3


class OpsError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OperationsManager:
    def __init__(self, engine, ops_dir: Path, webhook_url: str | None = None):
        self.engine = engine
        self.dir = Path(ops_dir)
        self.webhook_url = webhook_url or None
        self.tasks: list[dict] = []
        self._next = 1
        self.notifications: deque = deque(maxlen=100)
        self._note_id = 0
        self.auto_dispatch = True
        self.auto_load = False
        self.battery = 100.0
        self.battery_state = "idle"  # idle | discharging | charging | returning
        self.mode = "idle"  # idle | task | returning | charging
        self.charge_cycles = 0
        self._last_pose = None
        self._leg_mission = None
        self._arrived_at = None
        self._lock = threading.RLock()
        self.history = self._load_history()
        self._next = max((h.get("id", 0) for h in self.history), default=0) + 1

    # ------------------------------------------------------------ helpers
    def _place(self, key: str):
        p = next((pl for pl in self.engine.scenario.places if pl.key == key), None)
        if p is None:
            raise OpsError("unknown_place", f"No place '{key}' in this scenario", 422)
        return p

    def _dock(self):
        return next((pl for pl in self.engine.scenario.places if pl.key == "charging"), None)

    def notify(self, text: str, to: str = "operator", level: str = "info", task: int | None = None) -> None:
        self._note_id += 1
        note = {"id": self._note_id, "time": _now_iso(), "sim_time": round(self.engine.sim_time, 1), "to": to,
                "level": level, "text": text, "task": task, "webhook": None}
        self.notifications.append(note)
        self.engine._event(level if level in ("info", "warning", "success", "error") else "info", "operations", text)
        if self.webhook_url:
            note["webhook"] = "sending"
            threading.Thread(target=self._post_webhook, args=(note,), daemon=True).start()

    def _post_webhook(self, note: dict) -> None:
        """Forward a notification to an external service (e.g. an SMS or chat gateway)."""
        try:
            body = json.dumps({"source": "vistara-x", **{k: note[k] for k in ("time", "to", "level", "text", "task")}}).encode()
            req = urllib.request.Request(self.webhook_url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                note["webhook"] = f"sent ({resp.status})"
        except Exception as exc:  # never let a notification failure affect the robot
            note["webhook"] = f"failed ({type(exc).__name__})"

    def _log_done(self, task: dict) -> None:
        rec = {k: v for k, v in task.items() if k != "pin"}
        self.history.append(rec)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / "deliveries.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError as exc:
            log.warning("Could not write the delivery log: %s", exc)

    def _load_history(self) -> list[dict]:
        path = self.dir / "deliveries.jsonl"
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _public(self, t: dict, with_pin: bool = False) -> dict:
        return {k: v for k, v in t.items() if with_pin or k != "pin"}

    # ------------------------------------------------------------ commands
    def create_task(self, pickup: str, dropoff: str, item: str = "package", priority: str = "normal",
                    requested_by: str = "operator", recipient: str = "recipient") -> dict:
        with self._lock:
            if priority not in PRIORITIES:
                raise OpsError("invalid_priority", "Priority must be urgent, normal or low", 422)
            if pickup == dropoff:
                raise OpsError("same_place", "Pickup and drop-off must be different places", 422)
            a, b = self._place(pickup), self._place(dropoff)
            for p in (a, b):
                check = self.engine.preview_route(p.x, p.y)
                if not check["valid"]:
                    raise OpsError("invalid_place", f"{p.name} cannot be used now: {check['message']}", 409)
            task = {
                "id": self._next,
                "item": item.strip()[:60] or "package",
                "pickup": {"key": a.key, "name": a.name, "name_hi": a.name_hi, "x": a.x, "y": a.y},
                "dropoff": {"key": b.key, "name": b.name, "name_hi": b.name_hi, "x": b.x, "y": b.y},
                "priority": priority,
                "requested_by": requested_by.strip()[:40] or "operator",
                "recipient": recipient.strip()[:40] or "recipient",
                "pin": f"{secrets.randbelow(10000):04d}",
                "status": "queued",
                "scenario": self.engine.scenario.key,
                "created": _now_iso(),
                "created_sim": round(self.engine.sim_time, 1),
                "attempts": 0,
                "pin_tries": 0,
                "distance_m": 0.0,
                "timeline": [],
                "proof": None,
                "collisions": 0,
                "near_misses": 0,
            }
            self._next += 1
            self.tasks.append(task)
            self._mark(task, "queued", f"Requested by {task['requested_by']}")
            self.notify(f"Delivery #{task['id']} queued ({priority}): {task['item']} from {a.name} to {b.name}",
                        "requester", task=task["id"])
            return self._public(task, with_pin=True)

    def confirm_loaded(self, tid: int, by: str = "staff") -> dict:
        with self._lock:
            t = self._get(tid)
            if t["status"] != "loading":
                raise OpsError("not_loading", f"Delivery #{tid} is {t['status']}, not waiting at the pickup")
            self._mark(t, "to_dropoff", f"Loaded by {by}")
            self._start_leg(t, t["dropoff"])
            self.notify(f"Delivery #{tid}: {t['item']} loaded at {t['pickup']['name']}; on the way to {t['dropoff']['name']}",
                        t["recipient"], task=tid)
            return self._public(t)

    def deliver(self, tid: int, pin: str) -> dict:
        with self._lock:
            t = self._get(tid)
            if t["status"] != "awaiting_pin":
                raise OpsError("not_arrived", f"Delivery #{tid} is {t['status']}, not waiting for the recipient")
            if not secrets.compare_digest(str(pin), t["pin"]):
                t["pin_tries"] += 1
                if t["pin_tries"] >= MAX_PIN_TRIES:
                    self.notify(f"Delivery #{tid}: {MAX_PIN_TRIES} wrong PINs at {t['dropoff']['name']}; operator check needed",
                                "operator", "warning", tid)
                raise OpsError("wrong_pin", f"Wrong PIN ({t['pin_tries']} of {MAX_PIN_TRIES} tries)", 422)
            t["proof"] = {"method": "recipient PIN", "verified_at": _now_iso(), "verified_sim": round(self.engine.sim_time, 1),
                          "duration_s": round(self.engine.sim_time - t["created_sim"], 1)}
            self._mark(t, "delivered", "PIN verified")
            self.mode = "idle"
            self.notify(f"Delivery #{tid} delivered: {t['item']} handed over at {t['dropoff']['name']} (PIN verified)",
                        t["requested_by"], "success", tid)
            self._log_done(t)
            return self._public(t)

    def cancel(self, tid: int) -> dict:
        with self._lock:
            t = self._get(tid)
            if t["status"] in ("delivered", "failed", "cancelled"):
                raise OpsError("finished", f"Delivery #{tid} is already {t['status']}")
            active = t["status"] in ("to_pickup", "loading", "to_dropoff", "awaiting_pin")
            self._mark(t, "cancelled", "Cancelled by operator")
            if active:
                self.engine.emergency_stop()
                self.mode = "idle"
                self._leg_mission = None
            self.notify(f"Delivery #{tid} cancelled", t["requested_by"], "warning", tid)
            self._log_done(t)
            return self._public(t)

    def return_to_dock(self) -> dict:
        with self._lock:
            if self.mode == "task":
                raise OpsError("busy", "Finish or cancel the current delivery first")
            if not self._go_dock("Sent to the charging dock by the operator"):
                raise OpsError("no_dock", "This scenario has no charging dock")
            return self.snapshot()

    def configure(self, auto_dispatch=None, auto_load=None, battery=None) -> dict:
        with self._lock:
            if auto_dispatch is not None:
                self.auto_dispatch = bool(auto_dispatch)
            if auto_load is not None:
                self.auto_load = bool(auto_load)
            if battery is not None:
                self.battery = float(min(max(battery, 0.0), 100.0))  # demo control: set the charge level
            return self.snapshot()

    def reset(self) -> None:
        """Scenario changed: active and queued tasks refer to places that may not exist."""
        with self._lock:
            for t in self.tasks:
                if t["status"] not in ("delivered", "failed", "cancelled"):
                    self._mark(t, "cancelled", "Scenario reset")
                    self._log_done(t)
            self.mode = "idle"
            self._leg_mission = None
            self._last_pose = None

    # ------------------------------------------------------------ internals
    def _get(self, tid: int) -> dict:
        t = next((x for x in self.tasks if x["id"] == tid), None)
        if t is None:
            raise OpsError("not_found", f"No delivery #{tid}", 404)
        return t

    def _mark(self, t: dict, status: str, note: str = "") -> None:
        t["status"] = status
        t["timeline"].append({"status": status, "time": _now_iso(), "sim_time": round(self.engine.sim_time, 1), "note": note})

    def _start_leg(self, t: dict, place: dict) -> None:
        e = self.engine
        e.set_target(place["x"], place["y"])
        e.navigate()
        self._leg_mission = e.mission_id
        self._leg_start = (e.collisions, e.prediction.near_misses)
        self.mode = "task"
        self._arrived_at = None

    def _go_dock(self, why: str) -> bool:
        dock = self._dock()
        if dock is None:
            return False
        r = self.engine.world.robot
        if math.hypot(r.x - dock.x, r.y - dock.y) <= DOCK_RADIUS:
            self.mode = "charging"
            return True
        self.engine.set_target(dock.x, dock.y)
        self.engine.navigate()
        self._leg_mission = self.engine.mission_id
        self.mode = "returning"
        self.notify(f"{why} (battery {self.battery:.0f}%)", "operator", "warning" if self.battery < LOW else "info")
        return True

    def _next_task(self) -> dict | None:
        queued = [t for t in self.tasks if t["status"] == "queued"]
        if not queued:
            return None
        return min(queued, key=lambda t: (PRIORITIES[t["priority"]], t["id"]))

    def _active_task(self) -> dict | None:
        return next((t for t in self.tasks if t["status"] in ("to_pickup", "loading", "to_dropoff", "awaiting_pin")), None)

    def _account_leg(self, t: dict) -> None:
        e = self.engine
        c0, n0 = getattr(self, "_leg_start", (e.collisions, e.prediction.near_misses))
        t["collisions"] += max(e.collisions - c0, 0)
        t["near_misses"] += max(e.prediction.near_misses - n0, 0)
        self._leg_start = (e.collisions, e.prediction.near_misses)

    def tick(self) -> None:
        """Called by the engine after every step (engine lock held)."""
        with self._lock:
            e = self.engine
            r = e.world.robot
            dt = e.dt
            # Battery.
            moved = 0.0
            if self._last_pose is not None:
                moved = math.hypot(r.x - self._last_pose[0], r.y - self._last_pose[1])
            self._last_pose = (r.x, r.y)
            dock = self._dock()
            at_dock = dock is not None and math.hypot(r.x - dock.x, r.y - dock.y) <= DOCK_RADIUS and abs(r.v) < 0.05
            if at_dock and self.mode in ("idle", "charging", "returning") and e.status not in ("planning", "navigating", "replanning"):
                if self.mode != "charging":
                    self.mode = "charging"
                    self.notify(f"Docked; charging from {self.battery:.0f}%", "operator")
                was = self.battery
                self.battery = min(100.0, self.battery + CHARGE_PER_S * dt)
                if was < RESUME <= self.battery:
                    self.charge_cycles += 1
                    self.mode = "idle"
                    self.notify(f"Charged to {self.battery:.0f}%; ready for deliveries", "operator", "success")
                self.battery_state = "charging"
            else:
                self.battery = max(0.0, self.battery - DRAIN_PER_M * moved - DRAIN_PER_S * dt)
                self.battery_state = "returning" if self.mode == "returning" else ("discharging" if moved > 1e-4 else "idle")
            active = self._active_task()
            if active is not None and active["status"] in ("to_pickup", "to_dropoff"):
                active["distance_m"] = round(active["distance_m"] + moved, 2)

            # Follow the current leg.
            mine = self._leg_mission is not None and e.mission_id == self._leg_mission
            if self.mode in ("task", "returning") and self._leg_mission is not None and not mine:
                # The operator started another mission: step back, re-queue the delivery.
                if active is not None:
                    active["attempts"] += 1
                    self._mark(active, "queued", "Interrupted by a manual mission")
                self.mode = "idle"
                self._leg_mission = None
                return
            status = e.status
            if self.mode == "task" and active is not None and mine:
                if status == "goal_reached":
                    self._account_leg(active)
                    if active["status"] == "to_pickup":
                        self._mark(active, "loading", f"Arrived at {active['pickup']['name']}")
                        self._leg_mission = None
                        self._arrived_at = e.sim_time
                        self.notify(f"Delivery #{active['id']}: robot at {active['pickup']['name']}; load {active['item']} and confirm",
                                    "staff", task=active["id"])
                    elif active["status"] == "to_dropoff":
                        self._mark(active, "awaiting_pin", f"Arrived at {active['dropoff']['name']}")
                        self._leg_mission = None
                        self.notify(f"Delivery #{active['id']}: {active['item']} has arrived at {active['dropoff']['name']}; "
                                    f"enter your PIN to collect it", active["recipient"], "success", active["id"])
                elif status in ("blocked", "stopped", "error"):
                    self._account_leg(active)
                    active["attempts"] += 1
                    why = e.status_reason or status
                    if active["attempts"] < MAX_ATTEMPTS and active["status"] == "to_pickup":
                        self._mark(active, "queued", f"Attempt {active['attempts']} failed: {why}; re-queued")
                        self.notify(f"Delivery #{active['id']} could not reach {active['pickup']['name']} ({why}); will retry",
                                    "operator", "warning", active["id"])
                    else:
                        self._mark(active, "failed", why)
                        self.notify(f"Delivery #{active['id']} failed: {why}", active["requested_by"], "error", active["id"])
                        self._log_done(active)
                    self.mode = "idle"
                    self._leg_mission = None
            if (self.mode == "task" and active is not None and active["status"] == "loading" and self.auto_load
                    and self._arrived_at is not None and e.sim_time - self._arrived_at >= AUTO_LOAD_AFTER):
                self.confirm_loaded(active["id"], by="auto-load (demo)")
            if self.mode == "returning" and mine and status in ("blocked", "stopped", "error"):
                self.notify(f"Could not reach the charging dock: {e.status_reason or status}", "operator", "error")
                self.mode = "idle"
                self._leg_mission = None

            # Critical battery: abandon a pickup leg (nothing is being carried yet).
            if (self.battery < CRITICAL and self.mode == "task" and active is not None and active["status"] == "to_pickup"):
                self._mark(active, "queued", f"Battery critical ({self.battery:.0f}%); re-queued")
                e.emergency_stop()
                self._leg_mission = None
                self.mode = "idle"

            # Dispatch.
            if self.mode != "idle" or not self.auto_dispatch or active is not None:
                return
            if e.status in ("planning", "navigating", "replanning", "blocked_waiting", "paused"):
                return  # a manual mission is running
            if self.battery < LOW:
                self._go_dock("Battery low: returning to the charging dock")
                return
            nxt = self._next_task()
            if nxt is not None:
                self._mark(nxt, "to_pickup", f"Dispatched (attempt {nxt['attempts'] + 1})")
                self._start_leg(nxt, nxt["pickup"])
                self.notify(f"Delivery #{nxt['id']} started: heading to {nxt['pickup']['name']}", nxt["requested_by"], task=nxt["id"])

    # ------------------------------------------------------------ readers
    def _finished(self) -> dict:
        """Finished tasks from the log file and this session, keyed by (created, id)."""
        done = {(t["created"], t["id"]): t for t in self.history}
        for t in self.tasks:
            if t["status"] in ("delivered", "failed", "cancelled"):
                done[(t["created"], t["id"])] = self._public(t)
        return done

    def snapshot(self) -> dict:
        with self._lock:
            active = self._active_task()
            queued = sorted((t for t in self.tasks if t["status"] == "queued"), key=lambda t: (PRIORITIES[t["priority"]], t["id"]))
            return {
                "mode": self.mode,
                "auto_dispatch": self.auto_dispatch,
                "auto_load": self.auto_load,
                "battery": {
                    "level": round(self.battery, 1),
                    "state": self.battery_state,
                    "low": LOW,
                    "critical": CRITICAL,
                    "charge_cycles": self.charge_cycles,
                    "rates": "demo-accelerated: 0.4 %/m driven, 0.01 %/s idle, +2 %/s at the dock",
                },
                "dock": bool(self._dock()),
                "active": self._public(active) if active else None,
                "queue": [self._public(t) for t in queued],
                "recent": [self._public(t) for t in self.tasks[-12:]][::-1],
                "notifications": list(self.notifications)[-15:][::-1],
                "webhook": bool(self.webhook_url),
            }

    def report(self) -> dict:
        with self._lock:
            rows = list(self._finished().values())
            delivered = [t for t in rows if t["status"] == "delivered"]
            durations = [t["proof"]["duration_s"] for t in delivered if t.get("proof")]
            by_day: dict[str, int] = {}
            for t in delivered:
                day = (t.get("proof") or {}).get("verified_at", t["created"])[:10]
                by_day[day] = by_day.get(day, 0) + 1
            return {
                "generated_at": _now_iso(),
                "tasks_total": len(rows),
                "delivered": len(delivered),
                "failed": sum(1 for t in rows if t["status"] == "failed"),
                "cancelled": sum(1 for t in rows if t["status"] == "cancelled"),
                "mean_delivery_time_s": round(sum(durations) / len(durations), 1) if durations else None,
                "total_distance_m": round(sum(t.get("distance_m", 0) for t in rows), 1),
                "collisions": sum(t.get("collisions", 0) for t in rows),
                "near_misses": sum(t.get("near_misses", 0) for t in rows),
                "by_priority": {p: sum(1 for t in delivered if t["priority"] == p) for p in PRIORITIES},
                "delivered_per_day": by_day,
                "charge_cycles": self.charge_cycles,
                "note": "Simulated operations. Times are simulation seconds; battery rates are demo-accelerated.",
            }

    def report_csv(self) -> str:
        with self._lock:
            done = self._finished()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "scenario", "item", "pickup", "dropoff", "priority", "requested_by", "recipient", "status",
                    "created", "delivered_at", "duration_s", "distance_m", "attempts", "collisions", "near_misses"])
        for t in sorted(done.values(), key=lambda x: x["id"]):
            proof = t.get("proof") or {}
            w.writerow([t["id"], t.get("scenario"), t["item"], t["pickup"]["name"], t["dropoff"]["name"], t["priority"],
                        t["requested_by"], t["recipient"], t["status"], t["created"], proof.get("verified_at", ""),
                        proof.get("duration_s", ""), t.get("distance_m", 0), t.get("attempts", 0), t.get("collisions", 0),
                        t.get("near_misses", 0)])
        return buf.getvalue()
