"""Pure-pursuit waypoint follower for a differential-drive (unicycle) robot."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..simulation.world import RobotState


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


@dataclass
class ControlCommand:
    v: float
    w: float
    lookahead: tuple[float, float]
    segment_index: int  # index of the waypoint the robot is heading towards


@dataclass
class PurePursuitController:
    lookahead: float = 0.7
    max_speed: float = 1.0  # m/s
    max_omega: float = 2.2  # rad/s
    max_accel: float = 1.2  # m/s^2
    max_alpha: float = 6.0  # rad/s^2
    heading_gain: float = 2.8
    goal_slowdown: float = 1.2  # metres before the goal where we start slowing
    rotate_in_place: float = math.radians(65)

    def _closest_on_path(self, path, x, y, start_seg):
        best = (float("inf"), start_seg, 0.0)
        for i in range(start_seg, len(path) - 1):
            (ax, ay), (bx, by) = path[i], path[i + 1]
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg2))
            d = math.hypot(ax + t * dx - x, ay + t * dy - y)
            if d < best[0] - 1e-9:
                best = (d, i, t)
        return best[1], best[2]

    def _lookahead_point(self, path, seg, t):
        remaining = self.lookahead
        (ax, ay), (bx, by) = path[seg], path[seg + 1]
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        i = seg
        while True:
            nx, ny = path[i + 1]
            d = math.hypot(nx - px, ny - py)
            if d >= remaining or i + 1 == len(path) - 1:
                if d <= 1e-9:
                    return (nx, ny), i
                f = min(remaining / d, 1.0)
                return (px + (nx - px) * f, py + (ny - py) * f), i
            remaining -= d
            px, py = nx, ny
            i += 1

    def compute(
        self,
        robot: RobotState,
        path: list[tuple[float, float]],
        start_seg: int,
        dt: float,
        speed_limit: float,
    ) -> ControlCommand:
        if len(path) < 2:
            return ControlCommand(0.0, 0.0, (robot.x, robot.y), 0)
        seg, t = self._closest_on_path(path, robot.x, robot.y, start_seg)
        target, target_seg = self._lookahead_point(path, seg, t)
        heading_err = wrap_angle(math.atan2(target[1] - robot.y, target[0] - robot.x) - robot.theta)

        goal = path[-1]
        dist_goal = math.hypot(goal[0] - robot.x, goal[1] - robot.y)
        v_des = min(self.max_speed, speed_limit)
        v_des *= max(0.0, math.cos(heading_err))
        if abs(heading_err) > self.rotate_in_place:
            v_des = 0.0
        if dist_goal < self.goal_slowdown:
            v_des = min(v_des, max(0.15, self.max_speed * dist_goal / self.goal_slowdown))
        w_des = max(-self.max_omega, min(self.max_omega, self.heading_gain * heading_err))

        # Acceleration limits.
        dv = max(-self.max_accel * dt, min(self.max_accel * dt, v_des - robot.v))
        dw = max(-self.max_alpha * dt, min(self.max_alpha * dt, w_des - robot.w))
        return ControlCommand(robot.v + dv, robot.w + dw, target, seg + 1 if seg + 1 < len(path) else seg)


def integrate(robot: RobotState, v: float, w: float, dt: float) -> tuple[float, float, float]:
    """Unicycle kinematics (midpoint integration). Returns the new pose."""
    theta_mid = robot.theta + w * dt / 2
    x = robot.x + v * math.cos(theta_mid) * dt
    y = robot.y + v * math.sin(theta_mid) * dt
    return x, y, wrap_angle(robot.theta + w * dt)
