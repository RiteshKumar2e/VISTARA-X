"""Detector interface with two implementations.

* ``SimulatedDetector`` - derives detections from the renderer's object-id buffer
  (ground truth). It reports ``confidence = None`` and ``source = "ground_truth"``.
  It is NOT a model prediction and is labelled as such everywhere.
* ``YoloDetector`` - real Ultralytics YOLOv8 inference on the rendered camera frame.
  Enabled only when ``ultralytics`` imports and the weights file exists locally;
  we never download weights at runtime.
"""

from __future__ import annotations

import logging
import math
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from .camera import CameraFrame, box_for_columns

log = logging.getLogger("vistara.perception")

IGNORED_LABELS = {"wall"}


def _bearing(frame: CameraFrame, cx: float) -> float:
    """Bearing in degrees (positive = left of the optical axis) for an image column."""
    from .camera import FOV, IMG_W

    half = IMG_W / 2
    return math.degrees(math.atan((half - cx) / half * math.tan(FOV / 2)))


class Detector(Protocol):
    mode: str

    def detect(self, frame: CameraFrame) -> list[dict]: ...


class SimulatedDetector:
    mode = "simulated"
    description = "Simulated detector (ground-truth projection, not a model prediction)"

    def detect(self, frame: CameraFrame) -> list[dict]:
        if frame.seg is not None:
            return self._detect_from_mask(frame)
        detections = []
        idx = frame.hit_index
        for k in np.unique(idx):
            if k < 0:
                continue
            label = frame.labels[k]
            if label in IGNORED_LABELS:
                continue
            cols = np.nonzero(idx == k)[0]
            if len(cols) < 2:
                continue
            depth = float(frame.depth[cols].min())
            c0, c1 = int(cols.min()), int(cols.max())
            detections.append(
                {
                    "object_id": frame.ids[k],
                    "label": label,
                    "confidence": None,
                    "bbox": box_for_columns(c0, c1, depth, frame.heights[k]),
                    "distance": round(depth, 2),
                    "bearing_deg": round(_bearing(frame, (c0 + c1) / 2), 1),
                    "source": "ground_truth",
                }
            )
        detections.sort(key=lambda d: d["distance"])
        return detections

    def _detect_from_mask(self, frame: CameraFrame) -> list[dict]:
        """Boxes from the PyBullet segmentation mask (still ground truth)."""
        detections = []
        for k in np.unique(frame.seg):
            if k < 0 or frame.labels[k] in IGNORED_LABELS:
                continue
            ys, xs = np.nonzero(frame.seg == k)
            if len(xs) < 6:
                continue
            depth = float(frame.depth_image[ys, xs].min())
            x1, x2 = int(xs.min()), int(xs.max()) + 1
            detections.append(
                {
                    "object_id": frame.ids[k],
                    "label": frame.labels[k],
                    "confidence": None,
                    "bbox": [x1, int(ys.min()), x2, int(ys.max()) + 1],
                    "distance": round(depth, 2),
                    "bearing_deg": round(_bearing(frame, (x1 + x2) / 2), 1),
                    "source": "ground_truth",
                }
            )
        detections.sort(key=lambda d: d["distance"])
        return detections


class YoloDetector:
    mode = "yolov8"
    description = "Ultralytics YOLOv8 inference on the rendered camera frame"

    def __init__(self, weights: str, confidence: float = 0.25):
        if not 0.0 < confidence < 1.0:
            raise ValueError("confidence must be between 0 and 1")
        self.weights = weights
        self.confidence = confidence
        self._model = None
        self._lock = threading.Lock()
        self.error: str | None = None

    @staticmethod
    def availability(weights: str) -> tuple[bool, str]:
        if not Path(weights).is_file():
            return False, "weights file not found"
        try:
            import ultralytics  # noqa: F401
        except Exception:  # pragma: no cover - depends on environment
            return False, "ultralytics package not installed"
        return True, "ready"

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from ultralytics import YOLO

            self._model = YOLO(self.weights)
            log.info("Loaded YOLOv8 weights from %s", self.weights)

    def info(self) -> dict:
        if self._model is None:
            return {}
        return {"task": getattr(self._model, "task", None), "classes": len(getattr(self._model, "names", {}) or {})}

    def detect(self, frame: CameraFrame, conf: float | None = None, iou: float | None = None) -> list[dict]:
        self.load()
        results = self._model.predict(
            frame.image,
            imgsz=320,
            conf=self.confidence if conf is None else conf,
            iou=0.7 if iou is None else iou,
            verbose=False,
            device="cpu",
        )
        detections = []
        names = results[0].names
        if getattr(self._model, "task", "detect") != "detect" or results[0].boxes is None:
            raise ValueError(f"model task '{getattr(self._model, 'task', '?')}' is not object detection")
        for box in results[0].boxes:
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            c0, c1 = max(int(x1), 0), min(int(x2), len(frame.depth) - 1)
            depth = None
            if frame.depth_image is not None:
                # Range estimate: median depth of the pixels inside the box.
                region = frame.depth_image[max(int(y1), 0) : max(int(y2), int(y1) + 1), c0 : c1 + 1]
                if region.size:
                    depth = float(np.median(region))
            elif c1 >= c0:
                # Range estimate: median depth of the columns under the box.
                depth = float(np.median(frame.depth[c0 : c1 + 1]))
            detections.append(
                {
                    "object_id": None,
                    "label": names[int(box.cls[0])],
                    "confidence": round(float(box.conf[0]), 3),
                    "bbox": [round(x1), round(y1), round(x2), round(y2)],
                    "distance": round(depth, 2) if depth is not None else None,
                    "bearing_deg": round(_bearing(frame, (x1 + x2) / 2), 1),
                    "source": "yolov8",
                }
            )
        return detections
