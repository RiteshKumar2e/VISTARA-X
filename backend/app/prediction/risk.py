"""Motion prediction, conflict-risk estimation and the predictive speed decision.

Prediction: each track's Kalman state is propagated with the constant-velocity model;
its position uncertainty sigma(t) grows with the horizon (process noise).

Conflict test: the robot's own motion is rolled out along its planned route at a given
speed. At every time step t (0.1 s, up to 3 s) the robot and the obstacle are in
conflict when

    distance(robot(t), obstacle(t)) < robot radius + obstacle radius + safety margin + sigma(t)

The first such t is the time to collision (TTC) for that speed. It is reported only for
confirmed moving tracks with confidence >= MIN_TTC_CONFIDENCE; otherwise the track is
"uncertain" and only limits the speed.

Risk levels (rules, not probabilities):
- HIGH: a conflict is predicted within HIGH_TTC s at the current planned speed, or the
  obstacle is already inside the required separation.
- MEDIUM: a conflict is predicted within the 3 s horizon, or an uncertain track
  (coasting, tentative or low confidence) is within UNCERTAIN_NEAR m of the route ahead.
- LOW: neither.
A risk level is a rule-based estimate from a simple motion model. It is not a
probability of collision and does not guarantee that a collision cannot happen.

Decision (a sampling-based speed planner, not MPC): the speeds 100%, 50%, 25% and 0%
(wait) are each rolled out against all predictions; the fastest one with no predicted
conflict is chosen. If even waiting is in conflict (an object is heading for the robot's
position), the robot stops and the engine asks for a replan around the predicted path.
"""

from __future__ import annotations

import math

import numpy as np

from .tracker import MOVING_SPEED, predict_state

DT = 0.1
HORIZON = 3.0
TIMES = np.round(np.arange(DT, HORIZON + 1e-9, DT), 3)
SHOW_HORIZONS = (0.5, 1.0, 2.0, 3.0)
HIGH_TTC = 1.5
MIN_TTC_CONFIDENCE = 0.3
UNCERTAIN_NEAR = 1.5
UNCERTAIN_SPEED = 0.5
SPEED_OPTIONS = ((1.0, "continue"), (0.5, "slow"), (0.25, "crawl"), (0.0, "wait"))
# Prediction uncertainty: a pedestrian-like random acceleration of PRED_ACCEL_STD grows
# the position sigma with the horizon. It is capped at SIGMA_CAP, otherwise every
# option looks unsafe at 3 s and the robot never moves; tracks we cannot trust are
# handled separately (they cap the speed) instead of through a huge sigma.
PRED_ACCEL_STD = 0.35
SIGMA_CAP = 0.5


def robot_rollout(pose, path, wp_index, speed, times=TIMES) -> np.ndarray:
    """Robot positions at ``times`` when it follows the route at constant ``speed``."""
    pts = np.array([(pose[0], pose[1])] + [tuple(p) for p in path[max(wp_index, 1):]], dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T) if len(pts) > 1 else np.zeros(0)
    keep = np.concatenate([[True], seg > 1e-9])
    pts = pts[keep]
    cum = np.concatenate([[0.0], np.cumsum(seg[seg > 1e-9])])
    if len(pts) == 1:
        return np.repeat(pts, len(times), axis=0)
    s = np.minimum(speed * np.asarray(times), cum[-1])
    return np.column_stack([np.interp(s, cum, pts[:, 0]), np.interp(s, cum, pts[:, 1])])


def position_sigma(track, times):
    """Position std at ``times`` from the filter covariance plus prediction noise."""
    P = track.P
    t = np.asarray(times, dtype=float)
    var = ((P[0, 0] + P[1, 1]) + 2 * t * (P[0, 2] + P[1, 3]) + t**2 * (P[2, 2] + P[3, 3])) / 2
    var = var + PRED_ACCEL_STD**2 * t**4 / 4
    return np.minimum(np.sqrt(np.maximum(var, 0.0)), SIGMA_CAP)


def track_rollout(track, times=TIMES):
    """Predicted centre positions (constant velocity) and position sigma at ``times``."""
    t = np.asarray(times, dtype=float)
    if track.speed >= MOVING_SPEED:
        pos = np.column_stack([track.x[0] + track.x[2] * t, track.x[1] + track.x[3] * t])
    else:
        pos = np.repeat([[track.x[0], track.x[1]]], len(t), axis=0)
    return pos, position_sigma(track, t)


def obstacle_radius(track) -> float:
    return min(max(track.size / 2, 0.2), 0.6)


def first_conflict(robot_pos, obs_pos, sig, required) -> tuple[float | None, float]:
    """(time of first conflict or None, smallest margin) for one rollout."""
    d = np.hypot(robot_pos[:, 0] - obs_pos[:, 0], robot_pos[:, 1] - obs_pos[:, 1])
    margin = d - (required + sig)
    bad = np.nonzero(margin < 0)[0]
    return (float(TIMES[bad[0]]) if len(bad) else None), float(margin.min())


def near_route(track, robot_pos, dist: float) -> bool:
    d = np.hypot(robot_pos[:, 0] - track.x[0], robot_pos[:, 1] - track.x[1])
    return bool(d.min() < dist)


def assess(pose, path, wp_index, nominal_speed, tracks, robot_radius, safety_margin) -> dict:
    """Risk and predictive decision for the current tick."""
    if len(path) < 2 or nominal_speed <= 0:
        return {"risk": "LOW", "action": "continue", "speed_factor": 1.0, "ttc": None, "track": None,
                "reason": "No active route", "conflicts": [], "per_track": {}}
    nominal = robot_rollout(pose, path, wp_index, nominal_speed)
    per_track = {}
    reliable, uncertain = [], []
    for t in tracks:
        if t.state == "tentative":
            continue
        pos, sig = track_rollout(t)
        required = robot_radius + obstacle_radius(t) + safety_margin
        ttc, margin = first_conflict(nominal, pos, sig, required)
        moving = t.speed >= MOVING_SPEED
        trustworthy = t.state == "confirmed" and t.confidence() >= MIN_TTC_CONFIDENCE
        now_d = math.hypot(t.x[0] - pose[0], t.x[1] - pose[1]) - required
        if trustworthy and moving:
            level = "HIGH" if (ttc is not None and ttc <= HIGH_TTC) or now_d < 0 else ("MEDIUM" if ttc is not None else "LOW")
            reliable.append((t, pos, sig, required))
        else:
            near = near_route(t, nominal[: int(2.0 / DT)], UNCERTAIN_NEAR + required)
            level = "MEDIUM" if near and not (t.state == "confirmed" and not moving) else "LOW"
            if near and t.state != "confirmed":
                uncertain.append(t)
            ttc = None  # not meaningful for an untrustworthy or static track
        per_track[t.id] = {"risk": level, "ttc": ttc, "margin": round(margin, 2)}

    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    worst_id = max(per_track, key=lambda k: (order[per_track[k]["risk"]], -(per_track[k]["ttc"] or 9)), default=None)
    risk = per_track[worst_id]["risk"] if worst_id is not None else "LOW"

    # Predictive speed choice against the trustworthy moving tracks.
    chosen, conflicts, blocker = None, [], None
    for factor, name in SPEED_OPTIONS:
        roll = robot_rollout(pose, path, wp_index, nominal_speed * factor) if factor > 0 else np.repeat([[pose[0], pose[1]]], len(TIMES), axis=0)
        hit = None
        for t, pos, sig, req in reliable:
            ttc, _ = first_conflict(roll, pos, sig, req)
            if ttc is not None and (hit is None or ttc < hit[1]):
                hit = (t, ttc, pos[int(round(ttc / DT)) - 1])
        if hit is None:
            chosen = (factor, name)
            break
        if factor == 1.0:
            blocker = hit
            conflicts.append({"track": hit[0].id, "t": hit[1], "x": round(float(hit[2][0]), 2), "y": round(float(hit[2][1]), 2)})
    if chosen is None:
        chosen = (0.0, "stop")
    factor, action = chosen
    if uncertain and factor > UNCERTAIN_SPEED:
        factor, action = UNCERTAIN_SPEED, "slow"

    if blocker is not None:
        t, ttc, _ = blocker
        who = f"track {t.id} ({t.label})"
        reason = {
            "continue": f"Conflict with {who} predicted in {ttc:.1f} s",
            "slow": f"Predicted path conflict with {who} in {ttc:.1f} s: slowing to {int(factor * 100)}%",
            "crawl": f"Predicted path conflict with {who} in {ttc:.1f} s: slowing to {int(factor * 100)}%",
            "wait": f"Predicted path conflict with {who} in {ttc:.1f} s: waiting for it to pass",
            "stop": f"{who} is predicted to reach the robot: stopped, replanning around its predicted path",
        }[action]
        track_id, ttc_out = t.id, ttc
    elif uncertain:
        t = uncertain[0]
        reason = f"Uncertain track {t.id} ({t.state}) near the route: slowing to {int(factor * 100)}%"
        track_id, ttc_out = t.id, None
    else:
        reason = "No predicted conflicts"
        track_id, ttc_out = worst_id if risk != "LOW" else None, None
    return {
        "risk": risk,
        "action": action,
        "speed_factor": factor,
        "ttc": ttc_out,
        "track": track_id,
        "reason": reason,
        "conflicts": conflicts,
        "per_track": per_track,
    }


def predicted_mask(tracks, rows, cols, res, inflation, horizon=2.5):
    """Cells swept by trustworthy moving tracks over ``horizon`` (for replanning)."""
    yy, xx = np.mgrid[0:rows, 0:cols]
    cx, cy = (xx + 0.5) * res, (yy + 0.5) * res
    mask = np.zeros((rows, cols), dtype=bool)
    for t in tracks:
        if t.state != "confirmed" or t.speed < MOVING_SPEED:
            continue
        taus = np.arange(0.0, horizon + 1e-9, 0.25)
        pos, sig = track_rollout(t, taus)
        for (px, py), s in zip(pos, sig):
            mask |= np.hypot(cx - px, cy - py) < inflation + obstacle_radius(t) + s
    return mask
