"""2D LiDAR SLAM: wheel-odometry prediction + correlative scan matching + log-odds mapping.

For every LiDAR scan the pose estimate is first moved by the odometry increment since
the previous scan, then corrected by searching a small window of poses for the one
whose scan end points best fit the obstacles already in the map (a likelihood field,
as in correlative scan matching). The scan is then fused into the map at the corrected
pose. Without loop closure, error can still accumulate on long runs; the session
reports its own pose error against the simulator's ground truth so that this is
measured, not assumed.

The map frame equals the simulator's world frame and starts at the robot's known
initial pose.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import distance_transform_edt

from .occupancy import OCCUPIED, LogOddsMap

MATCH_SIGMA = 0.10  # m: likelihood-field spread around mapped obstacles
MIN_OCCUPIED_FOR_MATCH = 40  # mapped obstacle cells needed before scan matching is trusted
MIN_MATCH_SCORE = 0.25  # mean likelihood below which a match is rejected (poor overlap)
MAX_MATCH_POINTS = 120
TRAJECTORY_STEP = 0.10  # m between stored trajectory points
MAX_TRAJECTORY = 2000


def _wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


def compose(pose, delta):
    """pose (+) delta, with delta expressed in the pose's own frame."""
    x, y, th = pose
    dx, dy, dth = delta
    c, s = math.cos(th), math.sin(th)
    return (x + c * dx - s * dy, y + s * dx + c * dy, _wrap(th + dth))


def relative(a, b):
    """Delta that takes pose a to pose b, in a's frame."""
    c, s = math.cos(a[2]), math.sin(a[2])
    dx, dy = b[0] - a[0], b[1] - a[1]
    return (c * dx + s * dy, -s * dx + c * dy, _wrap(b[2] - a[2]))


class ScanMatcher:
    """Coarse-to-fine exhaustive search over (dx, dy, dtheta) on a likelihood field."""

    def __init__(self, xy_window=0.16, xy_step=0.04, th_window=math.radians(4), th_step=math.radians(1)):
        self.xy = np.arange(-xy_window, xy_window + 1e-9, xy_step)
        self.th = np.arange(-th_window, th_window + 1e-9, th_step)
        self._field = None
        self._field_version = -1

    def field(self, grid: LogOddsMap) -> np.ndarray:
        if grid.version != self._field_version:
            occ = grid.states() == OCCUPIED
            if occ.any():
                d = distance_transform_edt(~occ) * grid.resolution
                self._field = np.exp(-(d**2) / (2 * MATCH_SIGMA**2)).astype(np.float32)
            else:
                self._field = np.zeros(occ.shape, dtype=np.float32)
            self._field_version = grid.version
        return self._field

    def _scores(self, grid, field, pose, ex, ey, xs, ys, ths):
        x0, y0, th0 = pose
        th = th0 + ths  # (T,)
        c, s = np.cos(th)[:, None], np.sin(th)[:, None]
        wx = c * ex[None, :] - s * ey[None, :]  # (T, N)
        wy = s * ex[None, :] + c * ey[None, :]
        px = x0 + xs[None, :, None, None] + wx[:, None, None, :]  # (T, X, 1, N)
        py = y0 + ys[None, None, :, None] + wy[:, None, None, :]  # (T, 1, Y, N)
        px, py = np.broadcast_arrays(px, py)
        # Bilinear interpolation between cell centres: sub-cell accuracy for the match.
        gx = (px - grid.origin[0]) / grid.resolution - 0.5
        gy = (py - grid.origin[1]) / grid.resolution - 0.5
        c0 = np.floor(gx).astype(int)
        r0 = np.floor(gy).astype(int)
        fx, fy = gx - c0, gy - r0
        inside = (r0 >= 0) & (r0 < grid.rows - 1) & (c0 >= 0) & (c0 < grid.cols - 1)
        r0 = np.clip(r0, 0, grid.rows - 2)
        c0 = np.clip(c0, 0, grid.cols - 2)
        v = (
            field[r0, c0] * (1 - fx) * (1 - fy)
            + field[r0, c0 + 1] * fx * (1 - fy)
            + field[r0 + 1, c0] * (1 - fx) * fy
            + field[r0 + 1, c0 + 1] * fx * fy
        )
        return np.where(inside, v, 0.0).mean(axis=-1)  # (T, X, Y)

    def match(self, grid: LogOddsMap, pose, rel_angles, ranges):
        """Return (pose, score, used_match). ``rel_angles`` are ray angles in the robot
        frame (radians), ``ranges`` NaN where nothing was hit."""
        hit = np.isfinite(ranges)
        if hit.sum() < 10:
            return pose, 0.0, False
        ex = ranges[hit] * np.cos(rel_angles[hit])
        ey = ranges[hit] * np.sin(rel_angles[hit])
        if len(ex) > MAX_MATCH_POINTS:
            idx = np.linspace(0, len(ex) - 1, MAX_MATCH_POINTS).astype(int)
            ex, ey = ex[idx], ey[idx]
        field = self.field(grid)
        best = pose
        best_score = 0.0
        # Coarse search, then a finer search around the coarse optimum.
        for xs, ys, ths in (
            (self.xy, self.xy, self.th),
            (self.xy / 4, self.xy / 4, self.th / 4),
        ):
            scores = self._scores(grid, field, best, ex, ey, xs, ys, ths)
            t, i, j = np.unravel_index(int(np.argmax(scores)), scores.shape)
            score = float(scores[t, i, j])
            if score >= best_score:
                best_score = score
                best = (best[0] + float(xs[i]), best[1] + float(ys[j]), _wrap(best[2] + float(ths[t])))
        if best_score < MIN_MATCH_SCORE:
            return pose, best_score, False
        return best, best_score, True


class SlamSession:
    def __init__(self, width: float, height: float, resolution: float = 0.1):
        self.map = LogOddsMap(width, height, resolution)
        self.matcher = ScanMatcher()
        self.enabled = True
        self.reset((0.0, 0.0, 0.0))

    def reset(self, start_pose) -> None:
        self.map.clear()
        self.estimate = tuple(start_pose)
        self._last_odom = None
        self._last_lidar_seq = None
        self.trajectory = [(round(start_pose[0], 3), round(start_pose[1], 3))]
        self.truth_trajectory = [(round(start_pose[0], 3), round(start_pose[1], 3))]
        self.last_scan_points: list[tuple[float, float]] = []
        self.match_score = None
        self.matched = 0
        self.unmatched = 0
        self.pose_error = 0.0
        self.heading_error_deg = 0.0
        self.max_pose_error = 0.0
        self.last_update_time = None
        self.odometry_used = True

    def step(self, odom_pose, lidar, true_pose, sim_time: float) -> None:
        """Called every simulation tick. ``odom_pose`` is the wheel-odometry estimate
        (None when the odometry sensor is off); ``lidar`` is the LiDAR sensor."""
        # Prediction from odometry runs every tick, so the estimate follows the robot
        # even between scans (and when the LiDAR is off).
        self.odometry_used = odom_pose is not None
        if odom_pose is not None:
            if self._last_odom is not None:
                self.estimate = compose(self.estimate, relative(self._last_odom, odom_pose))
            self._last_odom = tuple(odom_pose)
        else:
            self._last_odom = None

        reading = lidar.reading if lidar.enabled else None
        if self.enabled and reading is not None and reading["frame"] != self._last_lidar_seq:
            self._last_lidar_seq = reading["frame"]
            rel = np.radians(np.array([b for b, _ in reading["scan"]], dtype=float))
            ranges = np.array([np.nan if r is None else r for _, r in reading["scan"]], dtype=float)
            if self.map.scans > 0 and int((self.map.states() == OCCUPIED).sum()) >= MIN_OCCUPIED_FOR_MATCH:
                pose, score, used = self.matcher.match(self.map, self.estimate, rel, ranges)
                self.match_score = round(score, 3)
                if used:
                    self.estimate = pose
                    self.matched += 1
                else:
                    self.unmatched += 1
            x, y, th = self.estimate
            self.map.integrate(self.estimate, th + rel, ranges, lidar.max_range)
            hit = np.isfinite(ranges)
            a = th + rel[hit]
            self.last_scan_points = [
                (round(float(x + r * math.cos(t)), 2), round(float(y + r * math.sin(t)), 2))
                for r, t in zip(ranges[hit], a)
            ]
            self.last_update_time = sim_time

        ex, ey, eth = self.estimate
        tx, ty, tth = true_pose
        self.pose_error = math.hypot(ex - tx, ey - ty)
        self.heading_error_deg = abs(math.degrees(_wrap(eth - tth)))
        self.max_pose_error = max(self.max_pose_error, self.pose_error)
        if math.dist(self.trajectory[-1], (ex, ey)) >= TRAJECTORY_STEP:
            self.trajectory.append((round(ex, 3), round(ey, 3)))
            self.truth_trajectory.append((round(tx, 3), round(ty, 3)))
            if len(self.trajectory) > MAX_TRAJECTORY:
                self.trajectory.pop(0)
                self.truth_trajectory.pop(0)

    def localization(self, lidar_ok: bool) -> dict:
        """Localisation quality from the scan-match score (no ground truth involved)."""
        if not lidar_ok:
            quality = "dead_reckoning" if self.odometry_used else "lost"
        elif self.match_score is None:
            quality = "initialising"
        elif self.match_score >= 0.6:
            quality = "good"
        elif self.match_score >= MIN_MATCH_SCORE:
            quality = "fair"
        else:
            quality = "poor"
        return {
            "quality": quality,
            "match_score": self.match_score,
            "scans_matched": self.matched,
            "scans_unmatched": self.unmatched,
            "odometry": "used" if self.odometry_used else "unavailable (scan matching only)",
        }
