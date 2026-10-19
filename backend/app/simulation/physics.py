"""PyBullet integration (optional, headless by default).

* ``PyBulletScene`` mirrors the world (floor, boundary walls, obstacles, robot) in
  a PyBullet client. Obstacles are static collision bodies; the robot is moved
  kinematically each tick (``resetBasePositionAndOrientation``) by our own
  controller, so motion stays deterministic.
* ``PyBulletCollision`` answers clearance / contact queries with
  ``getClosestPoints`` and ``getContactPoints``. The engine uses it to verify
  collisions against PyBullet's geometry.
* ``PyBulletCamera`` renders RGB, depth and a segmentation mask from the robot's
  camera pose with the TinyRenderer (works without a GPU or display).

Each object owns its own PyBullet client, so the simulation thread and the
perception thread never share one (PyBullet clients are not thread-safe).
"""

from __future__ import annotations

import logging
import math

import numpy as np

from .world import ROBOT_RADIUS, Obstacle

log = logging.getLogger("vistara.physics")

try:  # pragma: no cover - availability depends on the machine
    import pybullet as pb

    PYBULLET_AVAILABLE = True
    PYBULLET_ERROR = ""
except Exception as exc:  # ImportError or a broken build
    pb = None
    PYBULLET_AVAILABLE = False
    PYBULLET_ERROR = f"pybullet not importable ({type(exc).__name__})"

ROBOT_HEIGHT = 0.4
WALL_HEIGHT = 2.2
WALL_THICKNESS = 0.2

# RGB 0-1 colours per class for the rendered camera.
CLASS_RGB = {
    "shelf": (0.59, 0.43, 0.27),
    "pallet": (0.75, 0.55, 0.24),
    "person": (0.78, 0.27, 0.24),
    "barrier": (0.82, 0.63, 0.16),
    "cone": (0.90, 0.47, 0.12),
    "crate": (0.47, 0.47, 0.35),
    "wall": (0.80, 0.80, 0.78),
}


class PyBulletScene:
    def __init__(self, width: float, height: float, gui: bool = False):
        if not PYBULLET_AVAILABLE:
            raise RuntimeError(PYBULLET_ERROR)
        self.width, self.height = width, height
        self.client = pb.connect(pb.GUI if gui else pb.DIRECT)
        pb.setGravity(0, 0, -9.81, physicsClientId=self.client)
        self._bodies: dict[str, tuple[int, tuple]] = {}  # obstacle id -> (body, signature)
        self.body_to_obstacle: dict[int, str] = {}
        self.walls: list[int] = []
        self._build_static()
        self.robot = self._make_cylinder(ROBOT_RADIUS, ROBOT_HEIGHT, (0, 0, ROBOT_HEIGHT / 2),
                                         (0.95, 0.95, 0.95))

    # ------------------------------------------------------------- building
    def _make_box(self, half, pos, rgb):
        c = self.client
        col = pb.createCollisionShape(pb.GEOM_BOX, halfExtents=half, physicsClientId=c)
        vis = pb.createVisualShape(pb.GEOM_BOX, halfExtents=half, rgbaColor=(*rgb, 1), physicsClientId=c)
        return pb.createMultiBody(0, col, vis, basePosition=pos, physicsClientId=c)

    def _make_cylinder(self, r, h, pos, rgb):
        c = self.client
        col = pb.createCollisionShape(pb.GEOM_CYLINDER, radius=r, height=h, physicsClientId=c)
        vis = pb.createVisualShape(pb.GEOM_CYLINDER, radius=r, length=h, rgbaColor=(*rgb, 1),
                                   physicsClientId=c)
        return pb.createMultiBody(0, col, vis, basePosition=pos, physicsClientId=c)

    def _build_static(self):
        w, h, t = self.width, self.height, WALL_THICKNESS
        self.floor = self._make_box((w / 2, h / 2, 0.01), (w / 2, h / 2, -0.01), (0.86, 0.85, 0.82))
        wall_rgb = CLASS_RGB["wall"]
        for half, pos in [
            ((w / 2 + t, t / 2, WALL_HEIGHT / 2), (w / 2, -t / 2, WALL_HEIGHT / 2)),
            ((w / 2 + t, t / 2, WALL_HEIGHT / 2), (w / 2, h + t / 2, WALL_HEIGHT / 2)),
            ((t / 2, h / 2 + t, WALL_HEIGHT / 2), (-t / 2, h / 2, WALL_HEIGHT / 2)),
            ((t / 2, h / 2 + t, WALL_HEIGHT / 2), (w + t / 2, h / 2, WALL_HEIGHT / 2)),
        ]:
            self.walls.append(self._make_box(half, pos, wall_rgb))

    @staticmethod
    def _signature(o: Obstacle) -> tuple:
        return (o.shape, o.w, o.h, o.r, o.height, o.label)

    def sync(self, obstacles: list[Obstacle]) -> None:
        """Create, move or remove PyBullet bodies to match the obstacle list."""
        c = self.client
        seen = set()
        for o in obstacles:
            seen.add(o.id)
            sig = self._signature(o)
            entry = self._bodies.get(o.id)
            if entry and entry[1] != sig:
                pb.removeBody(entry[0], physicsClientId=c)
                self.body_to_obstacle.pop(entry[0], None)
                entry = None
            pos = (o.x, o.y, o.height / 2)
            if entry is None:
                rgb = CLASS_RGB.get(o.label, (0.5, 0.5, 0.5))
                if o.shape == "circle":
                    body = self._make_cylinder(o.r, o.height, pos, rgb)
                else:
                    body = self._make_box((o.w / 2, o.h / 2, o.height / 2), pos, rgb)
                self._bodies[o.id] = (body, sig)
                self.body_to_obstacle[body] = o.id
            else:
                pb.resetBasePositionAndOrientation(entry[0], pos, (0, 0, 0, 1), physicsClientId=c)
        for oid in [k for k in self._bodies if k not in seen]:
            body = self._bodies.pop(oid)[0]
            pb.removeBody(body, physicsClientId=c)
            self.body_to_obstacle.pop(body, None)

    def set_robot(self, x: float, y: float, theta: float) -> None:
        orn = pb.getQuaternionFromEuler((0, 0, theta))
        pb.resetBasePositionAndOrientation(self.robot, (x, y, ROBOT_HEIGHT / 2), orn,
                                           physicsClientId=self.client)

    def close(self) -> None:
        try:
            pb.disconnect(physicsClientId=self.client)
        except Exception:
            pass


class PyBulletCollision(PyBulletScene):
    """Clearance and contact queries between the robot and the scene."""

    backend = "pybullet"

    def clearance(self, x: float, y: float, max_distance: float = 5.0) -> tuple[float, str | None]:
        """Surface-to-surface distance from the robot footprint at (x, y) to the
        nearest obstacle or wall (negative = penetration), and what it is."""
        self.set_robot(x, y, 0.0)
        best, name = max_distance, None
        for body in list(self.body_to_obstacle) + self.walls:
            pts = pb.getClosestPoints(self.robot, body, max_distance, physicsClientId=self.client)
            for p in pts:
                if p[8] < best:
                    best = p[8]
                    name = self.body_to_obstacle.get(body, "boundary")
        return best, name

    def contacts(self) -> list[str]:
        pb.performCollisionDetection(physicsClientId=self.client)
        names = set()
        for p in pb.getContactPoints(bodyA=self.robot, physicsClientId=self.client):
            if p[2] != self.floor:
                names.add(self.body_to_obstacle.get(p[2], "boundary"))
        return sorted(names)


class AnalyticCollision:
    """Fallback when PyBullet is unavailable: exact 2D distance to the same geometry."""

    backend = "analytic"

    def __init__(self, width: float, height: float):
        self.width, self.height = width, height
        self._obstacles: list[Obstacle] = []

    def sync(self, obstacles: list[Obstacle]) -> None:
        self._obstacles = obstacles

    def clearance(self, x: float, y: float, max_distance: float = 5.0):
        best = min(x, y, self.width - x, self.height - y) - ROBOT_RADIUS
        name = "boundary"
        for o in self._obstacles:
            d = float(o.distance(x, y)) - ROBOT_RADIUS
            if d < best:
                best, name = d, o.id
        return min(best, max_distance), name

    def contacts(self) -> list[str]:
        return []

    def close(self) -> None:
        pass


class PyBulletCamera(PyBulletScene):
    """Forward camera rendered by PyBullet's TinyRenderer (CPU only)."""

    def render(self, pose, obstacles: list[Obstacle], width: int, height: int, hfov_deg: float,
               cam_height: float, max_range: float):
        self.sync(obstacles)
        x, y, theta = pose
        self.set_robot(x, y, theta)
        near, far = 0.05, max_range
        eye = (x + math.cos(theta) * (ROBOT_RADIUS + 0.02), y + math.sin(theta) * (ROBOT_RADIUS + 0.02),
               cam_height)
        target = (eye[0] + math.cos(theta), eye[1] + math.sin(theta), cam_height)
        view = pb.computeViewMatrix(eye, target, (0, 0, 1), physicsClientId=self.client)
        aspect = width / height
        vfov = math.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) / aspect))
        proj = pb.computeProjectionMatrixFOV(vfov, aspect, near, far, physicsClientId=self.client)
        _, _, rgba, depth_buf, seg = pb.getCameraImage(
            width, height, view, proj, renderer=pb.ER_TINY_RENDERER, physicsClientId=self.client
        )
        rgba = np.reshape(np.asarray(rgba, dtype=np.uint8), (height, width, 4))
        depth_buf = np.reshape(np.asarray(depth_buf, dtype=np.float32), (height, width))
        seg = np.reshape(np.asarray(seg, dtype=np.int64), (height, width))
        depth = far * near / (far - (far - near) * depth_buf)  # linearise the z-buffer
        # Map PyBullet body ids to indices in `obstacles`; -1 = wall, -2 = floor/sky.
        index_of = {o.id: i for i, o in enumerate(obstacles)}
        body = seg & ((1 << 24) - 1)
        seg_idx = np.full_like(body, -2)
        for b, oid in self.body_to_obstacle.items():
            if oid in index_of:
                seg_idx[body == b] = index_of[oid]
        for w in self.walls:
            seg_idx[body == w] = -1
        bgr = rgba[:, :, 2::-1].copy()
        return bgr, depth, seg_idx
