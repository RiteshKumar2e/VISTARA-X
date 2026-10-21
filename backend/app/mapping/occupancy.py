"""Log-odds occupancy grid built from range scans, plus ROS map_server import/export.

Each scan ray marks the cells it passes through as more likely free and the cell at
its end point (when the ray hit something) as more likely occupied. Cells no ray has
touched stay unknown. The PGM + YAML format is the one ROS map_server / Nav2 use, so a
map saved here opens in those tools and a map exported from them can be imported.
"""

from __future__ import annotations

import io
import math
import re

import numpy as np

L_OCC = 0.85  # log-odds added at a ray's end point (p ~ 0.70)
L_FREE = -0.40  # log-odds added along a ray (p ~ 0.40)
L_MIN, L_MAX = -4.0, 4.0
OCC_THRESHOLD = 0.6  # log-odds above this: occupied (p > 0.65)
FREE_THRESHOLD = -0.3  # below this: free (p < 0.43); one clear ray pass is enough

# Cell states used everywhere (API, planner, PGM).
UNKNOWN, FREE, OCCUPIED = 0, 1, 2


class LogOddsMap:
    def __init__(self, width: float, height: float, resolution: float = 0.1, origin=(0.0, 0.0)):
        self.width, self.height, self.resolution = width, height, resolution
        self.origin = (float(origin[0]), float(origin[1]))
        self.cols = int(math.ceil(width / resolution))
        self.rows = int(math.ceil(height / resolution))
        self.logodds = np.zeros((self.rows, self.cols), dtype=np.float32)
        self.touched = np.zeros((self.rows, self.cols), dtype=bool)
        self.scans = 0
        self.version = 0

    def clear(self) -> None:
        self.logodds[:] = 0
        self.touched[:] = False
        self.scans = 0
        self.version += 1

    # ------------------------------------------------------------ geometry
    def to_cells(self, xs, ys):
        cols = np.floor((np.asarray(xs) - self.origin[0]) / self.resolution).astype(int)
        rows = np.floor((np.asarray(ys) - self.origin[1]) / self.resolution).astype(int)
        return rows, cols

    def _inside(self, rows, cols):
        return (rows >= 0) & (rows < self.rows) & (cols >= 0) & (cols < self.cols)

    # ------------------------------------------------------------ update
    def integrate(self, pose, angles, ranges, max_range: float) -> None:
        """Fuse one scan. ``angles`` are world-frame ray angles; ``ranges`` hold NaN
        for rays that returned nothing within ``max_range`` (free up to max range)."""
        x, y, _ = pose
        angles = np.asarray(angles, dtype=float)
        ranges = np.asarray(ranges, dtype=float)
        hit = np.isfinite(ranges)
        reach = np.where(hit, ranges, max_range)
        step = self.resolution * 0.5
        n = int(np.ceil(max_range / step))
        t = np.arange(n) * step  # sample distances along each ray
        # Free samples stop half a cell before the end point so the hit cell is not freed.
        mask = t[None, :] < (reach[:, None] - self.resolution * 0.5)
        px = x + np.cos(angles)[:, None] * t[None, :]
        py = y + np.sin(angles)[:, None] * t[None, :]
        fr, fc = self.to_cells(px[mask], py[mask])
        ok = self._inside(fr, fc)
        free_idx = np.unique(fr[ok] * self.cols + fc[ok])

        hx = x + np.cos(angles[hit]) * ranges[hit]
        hy = y + np.sin(angles[hit]) * ranges[hit]
        hr, hc = self.to_cells(hx, hy)
        ok = self._inside(hr, hc)
        occ_idx = np.unique(hr[ok] * self.cols + hc[ok])
        free_idx = np.setdiff1d(free_idx, occ_idx, assume_unique=True)

        flat = self.logodds.reshape(-1)
        flat[free_idx] += L_FREE
        flat[occ_idx] += L_OCC
        np.clip(flat, L_MIN, L_MAX, out=flat)
        touched = self.touched.reshape(-1)
        touched[free_idx] = True
        touched[occ_idx] = True
        self.scans += 1
        self.version += 1

    # ------------------------------------------------------------ readers
    def states(self) -> np.ndarray:
        s = np.full(self.logodds.shape, UNKNOWN, dtype=np.uint8)
        s[self.touched & (self.logodds < FREE_THRESHOLD)] = FREE
        s[self.touched & (self.logodds > OCC_THRESHOLD)] = OCCUPIED
        return s

    def stats(self) -> dict:
        s = self.states()
        total = s.size
        free = int((s == FREE).sum())
        occ = int((s == OCCUPIED).sum())
        return {
            "free_cells": free,
            "occupied_cells": occ,
            "unknown_cells": total - free - occ,
            "known_fraction": round((free + occ) / total, 4),
        }

    def to_rows(self) -> list[str]:
        """Row strings from row 0 (y = origin) upward: 'u' unknown, 'f' free, 'o' occupied."""
        lut = np.array(["u", "f", "o"])
        return ["".join(r) for r in lut[self.states()]]

    # ------------------------------------------------------------ ROS map_server format
    def to_pgm(self) -> bytes:
        """Binary PGM, ROS convention: occupied 0, free 254, unknown 205; the first image
        row is the top of the map (largest y)."""
        s = self.states()
        img = np.full(s.shape, 205, dtype=np.uint8)
        img[s == FREE] = 254
        img[s == OCCUPIED] = 0
        img = np.flipud(img)
        header = f"P5\n# VISTARA-X occupancy map\n{self.cols} {self.rows}\n255\n".encode()
        return header + img.tobytes()

    def to_yaml(self, image_name: str) -> str:
        return (
            f"image: {image_name}\n"
            f"resolution: {self.resolution}\n"
            f"origin: [{self.origin[0]}, {self.origin[1]}, 0.0]\n"
            "negate: 0\n"
            "occupied_thresh: 0.65\n"
            "free_thresh: 0.196\n"
            "mode: trinary\n"
        )

    @classmethod
    def from_states(cls, states: np.ndarray, resolution: float, origin=(0.0, 0.0)) -> "LogOddsMap":
        rows, cols = states.shape
        m = cls(cols * resolution, rows * resolution, resolution, origin)
        m.logodds[states == FREE] = L_MIN
        m.logodds[states == OCCUPIED] = L_MAX
        m.touched[:] = states != UNKNOWN
        return m


class MapFormatError(ValueError):
    pass


def parse_yaml(text: str) -> dict:
    """The small subset of YAML that map_server files use (flat keys, one list)."""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        if value.startswith("["):
            try:
                out[key] = [float(v) for v in value.strip("[]").split(",")]
            except ValueError as exc:
                raise MapFormatError(f"'{key}' must be a list of numbers") from exc
        else:
            out[key] = value.strip("'\"")
    for key in ("resolution", "origin"):
        if key not in out:
            raise MapFormatError(f"Map YAML is missing '{key}'")
    try:
        out["resolution"] = float(out["resolution"])
        out["negate"] = int(out.get("negate", 0))
        out["occupied_thresh"] = float(out.get("occupied_thresh", 0.65))
        out["free_thresh"] = float(out.get("free_thresh", 0.196))
    except ValueError as exc:
        raise MapFormatError("resolution, negate and thresholds must be numbers") from exc
    if not 0.01 <= out["resolution"] <= 1.0:
        raise MapFormatError("resolution must be between 0.01 and 1.0 m per cell")
    if len(out["origin"]) < 2:
        raise MapFormatError("origin must be [x, y, yaw]")
    return out


def parse_pgm(data: bytes) -> np.ndarray:
    """8-bit binary (P5) or ASCII (P2) PGM -> uint8 array (first row = top)."""
    buf = io.BytesIO(data)
    tokens: list[bytes] = []
    while len(tokens) < 4:
        line = buf.readline()
        if not line:
            raise MapFormatError("PGM header is incomplete")
        line = line.split(b"#", 1)[0]
        tokens += line.split()
    magic, w, h, maxval = tokens[:4]
    try:
        w, h, maxval = int(w), int(h), int(maxval)
    except ValueError as exc:
        raise MapFormatError("PGM header has non-numeric size") from exc
    if not (1 <= w <= 4000 and 1 <= h <= 4000):
        raise MapFormatError("PGM image must be between 1 and 4000 pixels per side")
    if maxval > 255:
        raise MapFormatError("Only 8-bit PGM maps are supported")
    if magic == b"P5":
        raw = buf.read(w * h)
        if len(raw) < w * h:
            raise MapFormatError("PGM pixel data is truncated")
        img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w)
    elif magic == b"P2":
        vals = re.findall(rb"\d+", buf.read())
        if len(vals) < w * h:
            raise MapFormatError("PGM pixel data is truncated")
        img = np.array([int(v) for v in vals[: w * h]], dtype=np.uint8).reshape(h, w)
    else:
        raise MapFormatError("Not a PGM file (expected P5 or P2)")
    if maxval != 255:
        img = (img.astype(np.float32) * 255 / maxval).astype(np.uint8)
    return img


def states_from_image(img: np.ndarray, meta: dict) -> np.ndarray:
    """map_server trinary interpretation -> states with row 0 at the map origin."""
    p = img.astype(np.float32) / 255.0
    occ_prob = p if meta.get("negate", 0) else 1.0 - p
    s = np.full(img.shape, UNKNOWN, dtype=np.uint8)
    s[occ_prob > meta["occupied_thresh"]] = OCCUPIED
    s[occ_prob < meta["free_thresh"]] = FREE
    return np.flipud(s)


def resample(states: np.ndarray, src_res: float, src_origin, rows: int, cols: int, res: float):
    """Map states -> (occupied, unknown) masks on a coarser planning grid whose origin is
    (0, 0). A planning cell is occupied if any occupied map cell lies inside it (thin walls
    are never lost); it is unknown if the map cell under its centre is unknown or outside
    the map."""
    occupied = np.zeros((rows, cols), dtype=bool)
    sr, sc = np.nonzero(states == OCCUPIED)
    if len(sr):
        cx = src_origin[0] + (sc + 0.5) * src_res
        cy = src_origin[1] + (sr + 0.5) * src_res
        c = np.floor(cx / res).astype(int)
        r = np.floor(cy / res).astype(int)
        ok = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
        occupied[r[ok], c[ok]] = True
    gx = (np.arange(cols) + 0.5) * res
    gy = (np.arange(rows) + 0.5) * res
    mc = np.floor((gx - src_origin[0]) / src_res).astype(int)
    mr = np.floor((gy - src_origin[1]) / src_res).astype(int)
    inside = (mr[:, None] >= 0) & (mr[:, None] < states.shape[0]) & (mc[None, :] >= 0) & (mc[None, :] < states.shape[1])
    lookup = states[np.clip(mr, 0, states.shape[0] - 1)[:, None], np.clip(mc, 0, states.shape[1] - 1)[None, :]]
    unknown = ~inside | (lookup == UNKNOWN)
    return occupied, unknown & ~occupied
