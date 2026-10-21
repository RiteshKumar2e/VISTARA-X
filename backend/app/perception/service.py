"""Perception pipeline: camera render -> detector -> scene understanding.

Runs on its own worker thread (owned by the simulation engine) so that slow model
inference never stalls the fixed-timestep control loop.
"""

from __future__ import annotations

import logging
import math
import threading
import time

import cv2

from ..config import Settings
from ..scene.observation import ObservationMask
from ..scene.tracker import ObstacleTracker
from ..scene.understanding import summarise
from ..simulation.physics import PYBULLET_AVAILABLE, PYBULLET_ERROR, PyBulletCamera
from ..simulation.world import ROBOT_RADIUS
from .camera import CAM_HEIGHT, FOV, IMG_H, IMG_W, MAX_RANGE, render, render_pybullet
from ..config import BACKEND_DIR
from .detectors import SimulatedDetector
from .registry import ModelRegistry

log = logging.getLogger("vistara.perception")

MODES = ("simulated", "yolov8")
STALE_FRAMES = 3  # results older than this many frame periods are reported stale


class PerceptionService:
    def __init__(self, settings: Settings, world_size=(20.0, 12.0)):
        self.simulated = SimulatedDetector()
        self.registry = ModelRegistry(BACKEND_DIR / "models", [settings.yolo_weights], settings.yolo_confidence)
        requested = settings.detector_mode.lower()
        real = self.registry.real_models()
        if requested in ("yolo", "yolov8", "auto") and real:
            self.registry.select(primary=real[0])
        self.enabled = True
        self.rate_hz = settings.perception_hz
        self.world_size = world_size

        # Camera renderer: PyBullet TinyRenderer when available, else analytic ray casting.
        self.camera = None
        self.renderer_note = ""
        if settings.physics != "analytic" and PYBULLET_AVAILABLE:
            try:
                self.camera = PyBulletCamera(*world_size)
            except Exception as exc:  # pragma: no cover - environment specific
                self.renderer_note = f"PyBullet camera failed ({type(exc).__name__}); using ray casting"
                log.warning(self.renderer_note)
        elif not PYBULLET_AVAILABLE:
            self.renderer_note = f"{PYBULLET_ERROR}; using ray casting"
        self.renderer = "pybullet" if self.camera else "raycast"

        res = settings.grid_resolution
        self.observed = ObservationMask(
            int(math.ceil(world_size[1] / res)), int(math.ceil(world_size[0] / res)), res
        )
        self.tracker = ObstacleTracker()
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self.detections: list[dict] = []
        self.summary: dict = summarise([])
        self.frame_seq = 0
        self.frame_time: float | None = None  # wall clock of the last processed frame
        self.frame_sim_time: float | None = None
        self.inference_ms: float | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ control
    @property
    def mode(self) -> str:
        return "simulated" if self.registry.policy.primary == "simulated" else "yolov8"

    @property
    def yolo_available(self) -> bool:
        return bool(self.registry.real_models())

    @property
    def yolo_reason(self) -> str:
        if self.yolo_available:
            return "ready"
        if not self.registry.ultralytics_ok:
            return self.registry.ultralytics_reason
        return "no weights found in backend/models"

    def set_mode(self, mode: str) -> None:
        """Backwards-compatible switch: 'yolov8' selects the first available model."""
        if mode not in MODES:
            raise ValueError(f"Unknown detector mode '{mode}'")
        if mode == "yolov8" and not self.yolo_available:
            raise RuntimeError(f"YOLOv8 is unavailable: {self.yolo_reason}")
        self.select_models(primary="simulated" if mode == "simulated" else self.registry.real_models()[0], secondary=None, mode="single")

    def select_models(self, **kwargs) -> None:
        self.registry.select(**kwargs)
        with self._lock:
            self.last_error = None
            self.tracker.reset()  # tracks from another detector are not comparable

    def configure(self, enabled=None, rate_hz=None, confidence=None) -> None:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
                if not self.enabled:
                    self.detections = []
                    self.summary = summarise([])
            if rate_hz is not None:
                self.rate_hz = float(rate_hz)
            if confidence is not None:
                self.registry.select(confidence=float(confidence))

    @property
    def period(self) -> float:
        return 1.0 / self.rate_hz

    def clear(self) -> None:
        with self._lock:
            self.detections = []
            self.summary = summarise([])
            self.tracker.reset()
            self.observed.reset()

    def fresh_summary(self) -> dict:
        """Scene summary only while results are fresh; stale data never steers the robot."""
        with self._lock:
            if not self.enabled or self._stale():
                return summarise([])
            return self.summary

    def _stale(self) -> bool:
        return self.frame_time is None or time.time() - self.frame_time > STALE_FRAMES * self.period

    # ---------------------------------------------------------------- pipeline
    def process(self, pose, obstacles, world_w, world_h, sim_time: float = 0.0) -> str | None:
        """Render and detect. Returns an error message if the model failed."""
        if not self.enabled:
            return None
        if self.camera is not None:
            frame = render_pybullet(self.camera, pose, obstacles, world_w, world_h)
        else:
            frame = render(pose, obstacles, world_w, world_h)
        error = None
        frame_id = self.frame_seq + 1
        started = time.perf_counter()
        if self.mode == "simulated":
            detections = self.simulated.detect(frame)
            for d in detections:
                d.update(model="simulated", frame_id=frame_id, time=round(sim_time, 3))
        else:
            if not self.registry.should_process():
                return None  # adaptive stride: frame skipped (counted in the registry)
            try:
                detections, _meta = self.registry.infer(frame, frame_id, sim_time)
            except Exception as exc:  # keep the robot running on model failure
                failed = self.registry.policy.primary
                log.exception("Model %s failed", failed)
                error = f"Model {failed} failed ({type(exc).__name__}); switched to simulated detector"
                self.registry.select(primary="simulated", secondary=None, mode="single")
                with self._lock:
                    self.last_error = error
                detections = self.simulated.detect(frame)
                for d in detections:
                    d.update(model="simulated", frame_id=frame_id, time=round(sim_time, 3))
        elapsed = (time.perf_counter() - started) * 1000
        ok, buf = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with self._lock:
            if not self.enabled:
                return error  # disabled while this frame was in flight: discard it
            if frame.ray_angles is not None:
                self.observed.mark_rays(pose[:2], frame.ray_angles, frame.ray_ranges)
            self.tracker.update(detections, pose, sim_time)
            self.detections = detections
            self.summary = summarise(detections)
            self.inference_ms = round(elapsed, 1)
            self.frame_seq += 1
            self.frame_time = time.time()
            self.frame_sim_time = sim_time
            if ok:
                self._jpeg = buf.tobytes()
        return error

    def close(self) -> None:
        if self.camera is not None:
            self.camera.close()

    # ---------------------------------------------------------------- readers
    def jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def observed_mask(self):
        with self._lock:
            return self.observed.seen.copy()

    def camera_tracks(self, now: float) -> list[dict]:
        """Camera-derived tracks (label + world position), for labelling LiDAR tracks."""
        with self._lock:
            return self.tracker.snapshot(now)

    def snapshot(self, sim_time: float | None = None) -> dict:
        with self._lock:
            now = sim_time if sim_time is not None else (self.frame_sim_time or 0.0)
            return {
                "mode": self.mode,
                "source_label": (
                    f"YOLOv8 inference ({self.registry.policy.primary})"
                    if self.mode == "yolov8"
                    else "Simulated (ground truth)"
                ),
                "enabled": self.enabled,
                "rate_hz": self.rate_hz,
                "confidence_threshold": self.registry.policy.confidence,
                "renderer": self.renderer,
                # Actual sensor configuration, so overlays match what the camera sees.
                "camera": {
                    "fov_deg": round(math.degrees(FOV), 1),
                    "height": CAM_HEIGHT,
                    "range": MAX_RANGE,
                    "forward_offset": round(ROBOT_RADIUS + 0.02, 3),
                },
                "renderer_note": self.renderer_note,
                "yolo_available": self.yolo_available,
                "yolo_status": self.yolo_reason,
                "frame_seq": self.frame_seq,
                "frame_size": [IMG_W, IMG_H],
                "processing_ms": self.inference_ms,
                "stale": self.enabled and self._stale(),
                "last_error": self.last_error,
                "detections": list(self.detections),
                "scene": dict(self.summary),
                "tracks": self.tracker.snapshot(now),
                "rejected_detections": self.tracker.rejected,
                "explored": round(self.observed.coverage(), 3),
                "models": self.registry.snapshot(),
            }
