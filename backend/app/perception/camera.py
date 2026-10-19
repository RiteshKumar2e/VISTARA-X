"""Synthetic forward-facing camera.

Renders a simple perspective image from the robot pose by ray-casting against the
obstacle geometry (one ray per image column pair). Alongside the RGB frame it
returns a per-column depth buffer and object-id buffer, which the simulated
detector uses for ground-truth boxes and which is used to estimate range for
YOLOv8 boxes.

This is a rendered approximation, not a photorealistic sensor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..simulation.world import Obstacle

IMG_W, IMG_H = 320, 180
RAYS = IMG_W // 2
FOV = math.radians(70)
MAX_RANGE = 12.0
CAM_HEIGHT = 0.5  # metres above the floor
FOCAL = (IMG_W / 2) / math.tan(FOV / 2)

# BGR colours per semantic class (OpenCV order).
CLASS_COLOURS = {
    "shelf": (70, 110, 150),
    "pallet": (60, 140, 190),
    "person": (60, 70, 200),
    "barrier": (40, 160, 210),
    "cone": (30, 120, 230),
    "crate": (90, 120, 120),
    "wall": (175, 170, 165),
}


@dataclass
class CameraFrame:
    image: np.ndarray  # (H, W, 3) uint8 BGR
    depth: np.ndarray  # (W,) metres along the optical axis (nearest surface per column)
    hit_index: np.ndarray  # (W,) obstacle index, -1 = boundary wall, -2 = nothing
    labels: list[str]
    ids: list[str]
    heights: list[float]
    pose: tuple[float, float, float]
    renderer: str = "raycast"  # "raycast" (analytic) or "pybullet"
    seg: np.ndarray | None = None  # (H, W) obstacle index per pixel (pybullet only)
    depth_image: np.ndarray | None = None  # (H, W) metres (pybullet only)
    ray_angles: np.ndarray | None = None  # world-frame ray angles, for the explored-area map
    ray_ranges: np.ndarray | None = None  # metres to the first hit along each ray


def _ray_hits(ox, oy, dirs, obstacles: list[Obstacle], width, height):
    """Return (distance, index) per ray. Vectorised over rays."""
    dx, dy = dirs[:, 0], dirs[:, 1]
    n = len(dirs)
    best = np.full(n, np.inf)
    idx = np.full(n, -2, dtype=int)

    with np.errstate(divide="ignore", invalid="ignore"):
        # Map boundary (we are inside the box, take the exit distance).
        tx = np.where(dx > 0, (width - ox) / dx, np.where(dx < 0, -ox / dx, np.inf))
        ty = np.where(dy > 0, (height - oy) / dy, np.where(dy < 0, -oy / dy, np.inf))
        tb = np.minimum(tx, ty)
        mask = tb < best
        best[mask], idx[mask] = tb[mask], -1

        for k, obs in enumerate(obstacles):
            if obs.shape == "circle":
                fx, fy = ox - obs.x, oy - obs.y
                b = fx * dx + fy * dy
                c = fx * fx + fy * fy - obs.r * obs.r
                disc = b * b - c
                t = np.where(disc >= 0, -b - np.sqrt(np.maximum(disc, 0)), np.inf)
                t = np.where(t > 1e-6, t, np.inf)
            else:
                x0, x1 = obs.x - obs.w / 2, obs.x + obs.w / 2
                y0, y1 = obs.y - obs.h / 2, obs.y + obs.h / 2
                t1, t2 = (x0 - ox) / dx, (x1 - ox) / dx
                t3, t4 = (y0 - oy) / dy, (y1 - oy) / dy
                tmin = np.maximum(np.minimum(t1, t2), np.minimum(t3, t4))
                tmax = np.minimum(np.maximum(t1, t2), np.maximum(t3, t4))
                tmin = np.nan_to_num(tmin, nan=-np.inf)
                tmax = np.nan_to_num(tmax, nan=-np.inf)
                t = np.where((tmax >= tmin) & (tmax > 1e-6), np.maximum(tmin, 1e-6), np.inf)
            mask = t < best
            best[mask], idx[mask] = t[mask], k
    return best, idx


def render(
    pose: tuple[float, float, float],
    obstacles: list[Obstacle],
    world_w: float,
    world_h: float,
) -> CameraFrame:
    x, y, theta = pose
    # Column angles, left to right in the image = counter-clockwise to clockwise.
    offsets = np.arctan((np.arange(RAYS) + 0.5 - RAYS / 2) / (RAYS / 2) * math.tan(FOV / 2))
    angles = theta - offsets
    dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    dist, idx = _ray_hits(x, y, dirs, obstacles, world_w, world_h)
    depth = np.minimum(dist * np.cos(offsets), MAX_RANGE)  # perpendicular distance

    img = np.empty((IMG_H, IMG_W, 3), dtype=np.uint8)
    horizon = IMG_H // 2
    # Ceiling and floor gradients.
    img[:horizon] = np.linspace(236, 214, horizon, dtype=np.uint8)[:, None, None]
    img[horizon:] = np.linspace(200, 150, IMG_H - horizon, dtype=np.uint8)[:, None, None]

    heights = [o.height for o in obstacles]
    for col in range(RAYS):
        d = max(depth[col], 0.05)
        k = idx[col]
        if k == -2 or d >= MAX_RANGE:
            continue
        if k == -1:
            label, h = "wall", 2.2
        else:
            label, h = obstacles[k].label, heights[k]
        top = int(horizon - FOCAL * (h - CAM_HEIGHT) / d)
        bottom = int(horizon + FOCAL * CAM_HEIGHT / d)
        top, bottom = max(top, 0), min(bottom, IMG_H)
        shade = max(0.35, 1.0 - d / MAX_RANGE)
        colour = np.array(CLASS_COLOURS.get(label, (120, 120, 120))) * shade
        img[top:bottom, col * 2 : col * 2 + 2] = colour.astype(np.uint8)

    # Expand ray buffers to full image width.
    return CameraFrame(
        image=img,
        depth=np.repeat(depth, 2),
        hit_index=np.repeat(idx, 2),
        labels=[o.label for o in obstacles],
        ids=[o.id for o in obstacles],
        heights=heights,
        pose=pose,
        ray_angles=angles,
        ray_ranges=np.minimum(dist, MAX_RANGE),
    )


def render_pybullet(camera, pose, obstacles: list[Obstacle], world_w: float, world_h: float) -> CameraFrame:
    """Render with a PyBulletCamera; the analytic ray cast still provides the
    explored-area rays (cheap and independent of the renderer)."""
    rays = render_rays(pose, obstacles, world_w, world_h)
    bgr, depth_img, seg = camera.render(pose, obstacles, IMG_W, IMG_H, math.degrees(FOV), CAM_HEIGHT, MAX_RANGE)
    hit = seg >= -1
    masked = np.where(hit, depth_img, np.inf)
    col_depth = np.minimum(masked.min(axis=0), MAX_RANGE)
    rows = masked.argmin(axis=0)
    col_index = np.where(np.isfinite(masked.min(axis=0)), seg[rows, np.arange(IMG_W)], -2)
    return CameraFrame(
        image=np.ascontiguousarray(bgr),
        depth=col_depth,
        hit_index=col_index,
        labels=[o.label for o in obstacles],
        ids=[o.id for o in obstacles],
        heights=[o.height for o in obstacles],
        pose=pose,
        renderer="pybullet",
        seg=seg,
        depth_image=depth_img,
        ray_angles=rays[0],
        ray_ranges=rays[1],
    )


def render_rays(pose, obstacles: list[Obstacle], world_w: float, world_h: float):
    x, y, theta = pose
    offsets = np.arctan((np.arange(RAYS) + 0.5 - RAYS / 2) / (RAYS / 2) * math.tan(FOV / 2))
    angles = theta - offsets
    dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    dist, _ = _ray_hits(x, y, dirs, obstacles, world_w, world_h)
    return angles, np.minimum(dist, MAX_RANGE)


def box_for_columns(c0: int, c1: int, depth: float, obj_height: float) -> list[int]:
    """Image-space bounding box [x1, y1, x2, y2] for an object spanning columns."""
    horizon = IMG_H // 2
    d = max(depth, 0.05)
    top = int(horizon - FOCAL * (obj_height - CAM_HEIGHT) / d)
    bottom = int(horizon + FOCAL * CAM_HEIGHT / d)
    return [int(c0), max(top, 0), int(c1) + 1, min(bottom, IMG_H)]
