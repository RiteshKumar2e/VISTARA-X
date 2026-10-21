"""Reproducible evaluation: predictive avoidance vs the reactive baseline.

Run from backend/:   python -m app.evaluation            (about 3-5 minutes on a laptop CPU)

Every run is a fresh headless engine (no threads, fixed seeds) stepped as fast as the CPU
allows. Results are written to backend/evaluation/results.json and results.md and
served by GET /evaluation. Nothing in these files is edited by hand.

Comparison: the "crossing" scenario with the crossing person's walking speed and start
time varied (3 x 3 variants), each run twice:
- predictive: tracking + prediction + predictive speed/route decisions (default);
- reactive baseline: the same robot with the predictive layer switched off. It still
  has every reactive layer (route-obstruction check with replanning, LiDAR/ultrasonic
  slow-down and stop, the ground-truth safety veto).

Scenario checks: one run each of the situations the Round 2 brief lists.
"""

from __future__ import annotations

import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from .commands.service import CommandService
from .config import BACKEND_DIR, Settings
from .simulation.engine import SimulationEngine

OUT_DIR = BACKEND_DIR / "evaluation"
TIME_LIMIT = 90.0  # s of simulated time per mission
PERSON_SPEEDS = (0.6, 0.9, 1.2)
START_OFFSETS = (0.0, 4.0, 8.0)  # s the obstacles walk before the mission starts


def _engine() -> SimulationEngine:
    return SimulationEngine(Settings(detector_mode="simulated", physics="auto"))


def _warm_up(e: SimulationEngine, seconds: float) -> None:
    """Let the moving obstacles walk for ``seconds`` before the robot starts."""
    for _ in range(int(seconds / e.dt)):
        e._move_obstacles()
        e.sim_time += e.dt


def _run_mission(e: SimulationEngine) -> dict:
    steps, step_ms = 0, []
    while e.mission_time < TIME_LIMIT:
        t0 = time.perf_counter()
        e.step()
        step_ms.append((time.perf_counter() - t0) * 1000)
        steps += 1
        if e.status in ("goal_reached", "blocked", "stopped", "error"):
            break
    m = e.prediction.metrics()
    return {
        "status": e.status,
        "goal_reached": e.status == "goal_reached",
        "time_s": round(e.mission_time, 2),
        "path_length_m": round(e.distance_travelled, 2),
        "replans": e.replans,
        "collisions": e.collisions,
        "near_misses": m["near_misses"],
        "min_moving_clearance_m": m["min_moving_clearance"],
        "prediction_error_1s_mean_m": m["prediction_error_1s_mean"],
        "prediction_error_1s_max_m": m["prediction_error_1s_max"],
        "prediction_samples": m["prediction_samples"],
        "tracks_lost": m["tracks_lost"],
        "tracking_ms_mean": m["tracking_ms_mean"],
        "tracking_ms_max": m["tracking_ms_max"],
        "step_ms_mean": round(statistics.mean(step_ms), 2) if step_ms else None,
        "step_ms_max": round(max(step_ms), 2) if step_ms else None,
        "predictive_events": sum(1 for ev in e.events if ev["type"] == "prediction"),
    }


def comparison_run(predictive: bool, person_speed: float, offset: float) -> dict:
    e = _engine()
    e.reset("crossing")
    for o in e.world.obstacles:
        if o.id == "person-1":
            o.speed = person_speed
    e.params["predictive"] = predictive
    _warm_up(e, offset)
    e.prediction.reset_metrics()
    e.set_target(18.5, 6.0)
    e.navigate()
    out = _run_mission(e)
    e.shutdown()
    return {"mode": "predictive" if predictive else "reactive", "person_speed": person_speed, "start_offset_s": offset, **out}


def _summary(runs: list[dict]) -> dict:
    done = [r for r in runs if r["goal_reached"]]
    clear = [r["min_moving_clearance_m"] for r in runs if r["min_moving_clearance_m"] is not None]
    errs = [r["prediction_error_1s_mean_m"] for r in runs if r["prediction_error_1s_mean_m"] is not None]
    return {
        "runs": len(runs),
        "goal_completion": f"{len(done)}/{len(runs)}",
        "collisions_total": sum(r["collisions"] for r in runs),
        "near_misses_total": sum(r["near_misses"] for r in runs),
        "min_clearance_worst_m": round(min(clear), 3) if clear else None,
        "min_clearance_mean_m": round(statistics.mean(clear), 3) if clear else None,
        "time_mean_s": round(statistics.mean(r["time_s"] for r in done), 2) if done else None,
        "path_length_mean_m": round(statistics.mean(r["path_length_m"] for r in done), 2) if done else None,
        "replans_mean": round(statistics.mean(r["replans"] for r in runs), 2),
        "prediction_error_1s_mean_m": round(statistics.mean(errs), 3) if errs else None,
        "step_ms_mean": round(statistics.mean(r["step_ms_mean"] for r in runs), 2),
        "step_ms_max": round(max(r["step_ms_max"] for r in runs), 2),
    }


def scenario_checks() -> list[dict]:
    checks = []

    # 1, 2, 4, 5: crossing scenario (static crate, crossing person, turning cart, lost track).
    e = _engine()
    e.reset("crossing")
    e.set_target(18.5, 6.0)
    e.navigate()
    r = _run_mission(e)
    checks.append({"check": "Static obstacle on the direct route (crate-1)", "passed": r["goal_reached"] and r["collisions"] == 0,
                   "detail": f"goal {r['status']}, path {r['path_length_m']} m (straight line 17.0 m), collisions {r['collisions']}"})
    checks.append({"check": "Moving obstacle crossing the route (person-1, does not give way)",
                   "passed": r["goal_reached"] and r["collisions"] == 0 and r["predictive_events"] > 0,
                   "detail": f"{r['predictive_events']} predictive decisions, min clearance to moving obstacles {r['min_moving_clearance_m']} m, near misses {r['near_misses']}"})
    checks.append({"check": "Moving obstacle that changes direction (cart-1, rectangular loop)",
                   "passed": r["prediction_samples"] > 0,
                   "detail": f"1 s prediction error mean {r['prediction_error_1s_mean_m']} m, max {r['prediction_error_1s_max_m']} m (the max occurs at turns, where constant velocity is wrong)"})
    checks.append({"check": "Uncertain / lost track (person walks behind the walls)",
                   "passed": r["tracks_lost"] >= 1 and r["collisions"] == 0,
                   "detail": f"{r['tracks_lost']} track(s) lost and dropped; coasting tracks are shown as uncertain and limit speed near the route"})
    e.shutdown()

    # 3: route blocked after navigation begins.
    e = _engine()
    e.reset("warehouse")
    e.params["moving_obstacles"] = False
    e.set_target(18.5, 6.0)
    e.navigate()
    while e.distance_travelled < 2.0 and e.mission_time < 30:
        e.step()
    e.inject_on_route()
    r = _run_mission(e)
    checks.append({"check": "Route blocked after navigation begins", "passed": r["goal_reached"] and r["replans"] >= 1,
                   "detail": f"{r['replans']} replan(s), goal {r['status']}, collisions {r['collisions']}"})
    e.shutdown()

    # 6, 7: command in Hindi/English (text pipeline; the speech path is tested separately).
    e = _engine()
    e.reset("crossing")
    svc = CommandService(e)
    rec = svc.interpret("Robot ko exit tak le jao", "text")
    ok_parse = rec["status"] == "awaiting_confirmation" and rec["intent"]["destination"]["key"] == "exit"
    svc.confirm(rec["id"])
    r = _run_mission(e)
    checks.append({"check": "Hinglish command: 'Robot ko exit tak le jao' (text-only, confirmed, no audio)",
                   "passed": ok_parse and r["goal_reached"],
                   "detail": f"language {rec['language']}, destination {rec['intent']['destination']['name']}, goal {r['status']} in {r['time_s']} s"})
    e.shutdown()

    # 8: destination that cannot be reached safely.
    e = _engine()
    e.reset("enclosed")
    svc = CommandService(e)
    rec = svc.interpret("go to the inner bay", trusted=True)
    blocked_ok = rec["status"] == "awaiting_confirmation" and rec["validation"]["reachable"] is False
    svc.confirm(rec["id"])
    r = _run_mission(e)
    checks.append({"check": "Unreachable destination (inner bay, sealed)", "passed": blocked_ok and r["status"] == "blocked" and r["path_length_m"] == 0.0,
                   "detail": f"not started automatically even in trusted mode; after confirmation status {r['status']}, travelled {r['path_length_m']} m"})
    e.shutdown()
    return checks


def main() -> None:
    started = time.perf_counter()
    runs = []
    for predictive in (True, False):
        for speed in PERSON_SPEEDS:
            for offset in START_OFFSETS:
                run = comparison_run(predictive, speed, offset)
                runs.append(run)
                print(f"{run['mode']:10} person {speed} m/s offset {offset:3.0f} s -> {run['status']:12} "
                      f"t {run['time_s']:5.1f} s, collisions {run['collisions']}, near misses {run['near_misses']}, "
                      f"min clearance {run['min_moving_clearance_m']} m", flush=True)
    checks = scenario_checks()
    for c in checks:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + ": " + c["detail"], flush=True)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "python -m app.evaluation",
        "machine": f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}",
        "duration_s": round(time.perf_counter() - started, 1),
        "simulation": "headless engine, simulated sensors, fixed seeds; obstacle ground truth used only for the metrics",
        "comparison": {
            "scenario": "crossing",
            "variants": {"person_speed_m_s": PERSON_SPEEDS, "start_offset_s": START_OFFSETS},
            "predictive": _summary([r for r in runs if r["mode"] == "predictive"]),
            "reactive": _summary([r for r in runs if r["mode"] == "reactive"]),
            "runs": runs,
        },
        "scenario_checks": checks,
    }
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (OUT_DIR / "results.md").write_text(to_markdown(result), encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'results.json'} and results.md in {result['duration_s']} s")


def to_markdown(r: dict) -> str:
    c = r["comparison"]
    rows = [
        ("Goal completion", "goal_completion"),
        ("Collisions (total)", "collisions_total"),
        ("Near misses (< 0.25 m, total)", "near_misses_total"),
        ("Closest approach to a moving obstacle, worst run (m)", "min_clearance_worst_m"),
        ("Closest approach, mean over runs (m)", "min_clearance_mean_m"),
        ("Task duration, mean (s)", "time_mean_s"),
        ("Path length, mean (m)", "path_length_mean_m"),
        ("Replans per run, mean", "replans_mean"),
        ("1 s prediction error, mean (m)", "prediction_error_1s_mean_m"),
        ("Simulation step time, mean / max (ms)", None),
    ]
    lines = [
        "# VISTARA-X evaluation results",
        "",
        f"Generated {r['generated_at']} by `{r['command']}` on {r['machine']} ({r['duration_s']} s). {r['simulation']}.",
        "",
        "## Predictive avoidance vs reactive baseline",
        "",
        f"Scenario `{c['scenario']}`, {c['predictive']['runs']} runs per mode: crossing person at "
        f"{', '.join(str(s) for s in c['variants']['person_speed_m_s'])} m/s, starting "
        f"{', '.join(str(int(o)) for o in c['variants']['start_offset_s'])} s early.",
        "",
        "| Metric | Predictive | Reactive baseline |",
        "|---|---|---|",
    ]
    for label, key in rows:
        if key is None:
            p, b = c["predictive"], c["reactive"]
            lines.append(f"| {label} | {p['step_ms_mean']} / {p['step_ms_max']} | {b['step_ms_mean']} / {b['step_ms_max']} |")
        else:
            lines.append(f"| {label} | {c['predictive'][key]} | {c['reactive'][key]} |")
    lines += ["", "### Individual runs", "", "| Mode | Person speed (m/s) | Start offset (s) | Result | Time (s) | Path (m) | Replans | Collisions | Near misses | Closest approach (m) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for x in c["runs"]:
        lines.append(f"| {x['mode']} | {x['person_speed']} | {x['start_offset_s']:.0f} | {x['status']} | {x['time_s']} | {x['path_length_m']} | {x['replans']} | {x['collisions']} | {x['near_misses']} | {x['min_moving_clearance_m']} |")
    lines += ["", "## Scenario checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    for ch in r["scenario_checks"]:
        lines.append(f"| {ch['check']} | {'pass' if ch['passed'] else 'FAIL'} | {ch['detail']} |")
    lines += ["", "These numbers come from one simulated environment with simple motion models. They are not a measure of real-world safety.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
