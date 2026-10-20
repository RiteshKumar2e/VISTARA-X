"""Detector registry and execution policy for multiple YOLO-family models.

* Models are discovered from weight files (``*.pt``) in ``backend/models`` plus the
  configured ``VISTARA_YOLO_WEIGHTS``. Nothing is downloaded.
* Policy modes:
    - ``single``  - primary model on every processed frame (resource-constrained mode)
    - ``cascade`` - primary every frame; secondary only when a trigger class appears,
                    or a primary detection's confidence falls in the uncertainty band
    - ``multi``   - primary every frame; secondary on every Nth frame as well
* Fusion: class-aware NMS across models. Overlapping same-class boxes are merged into
  the highest-confidence box and the contributing models are listed. Agreement is
  reported, but confidence is NOT raised: two models seeing the same thing on the same
  frame are correlated, not independent confirmation.
* Latency budget: an exponential moving average of frame inference time drives an
  adaptive frame stride (process every k-th frame) and suspends the secondary model
  while over budget. Skipped frames are counted, never silently hidden.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("vistara.models")

LABEL_ALIASES = {"people": "person", "pedestrian": "person", "box": "crate", "carton": "crate"}
MAX_STRIDE = 4


def normalise_label(label: str) -> str:
    key = label.strip().lower()
    return LABEL_ALIASES.get(key, key)


def iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / area if area > 0 else 0.0


def fuse(detections: list[dict], iou_threshold: float) -> list[dict]:
    """Class-aware non-maximum suppression across models (see module docstring)."""
    kept: list[dict] = []
    for d in sorted(detections, key=lambda x: x.get("confidence") or 0.0, reverse=True):
        label = normalise_label(d["label"])
        match = next(
            (k for k in kept if normalise_label(k["label"]) == label and iou(k["bbox"], d["bbox"]) >= iou_threshold),
            None,
        )
        if match is None:
            kept.append({**d, "label": label, "models": [d["model"]], "agreement": False})
        elif d["model"] not in match["models"]:
            match["models"].append(d["model"])
            match["agreement"] = True
    return kept


@dataclass
class ModelEntry:
    key: str
    path: str | None
    detector: object  # has .detect(frame, conf, iou) and optional .load()/.info()
    kind: str = "yolo"
    status: str = "available"  # available | loaded | error
    error: str | None = None
    task: str | None = None
    classes: int | None = None
    device: str = "cpu"
    runs: int = 0
    latencies: deque = field(default_factory=lambda: deque(maxlen=50))

    def to_dict(self) -> dict:
        lat = list(self.latencies)
        return {
            "key": self.key,
            "kind": self.kind,
            "file": Path(self.path).name if self.path else None,
            "status": self.status,
            "error": self.error,
            "task": self.task,
            "classes": self.classes,
            "device": self.device,
            "runs": self.runs,
            "latency_ms": {
                "last": round(lat[-1], 1) if lat else None,
                "mean": round(statistics.fmean(lat), 1) if lat else None,
                "p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1) if lat else None,
                "samples": len(lat),
            },
        }


@dataclass
class Policy:
    mode: str = "single"
    primary: str = "simulated"
    secondary: str | None = None
    trigger_classes: list = field(default_factory=lambda: ["person"])
    uncertainty: tuple = (0.25, 0.5)
    multi_every: int = 3
    confidence: float = 0.25
    iou: float = 0.5
    latency_budget_ms: float = 250.0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["uncertainty"] = list(self.uncertainty)
        return d


class ModelRegistry:
    def __init__(self, models_dir: Path, extra_weights: list[str] | None = None, confidence: float = 0.25):
        self.entries: dict[str, ModelEntry] = {}
        self.policy = Policy(confidence=confidence)
        self.ultralytics_ok, self.ultralytics_reason = self._check_ultralytics()
        self.stride = 1
        self.ema_ms: float | None = None
        self.secondary_suspended = False
        self.frames_seen = 0
        self.frames_processed = 0
        self.frames_skipped = 0
        self.last_secondary_reason: str | None = None
        self._lock = threading.RLock()
        self.discover(models_dir, extra_weights or [])

    @staticmethod
    def _check_ultralytics():
        try:
            import ultralytics  # noqa: F401
        except Exception:
            return False, "ultralytics package not installed"
        return True, "ready"

    def discover(self, models_dir: Path, extra: list[str]) -> None:
        from .detectors import YoloDetector  # local import keeps this module light

        paths = sorted(Path(models_dir).glob("*.pt")) if Path(models_dir).is_dir() else []
        for p in [*paths, *(Path(e) for e in extra)]:
            if not p.is_file():
                continue
            key = p.stem
            if key in self.entries:
                continue
            entry = ModelEntry(key, str(p), YoloDetector(str(p), self.policy.confidence))
            if not self.ultralytics_ok:
                entry.status, entry.error = "error", self.ultralytics_reason
            self.entries[key] = entry

    def register(self, key: str, detector, kind: str = "custom") -> ModelEntry:
        """Register an in-process detector (used by tests and custom integrations)."""
        with self._lock:
            entry = ModelEntry(key, None, detector, kind=kind)
            self.entries[key] = entry
            return entry

    def real_models(self) -> list[str]:
        return [k for k, e in self.entries.items() if e.status != "error"]

    # ------------------------------------------------------------ selection
    def select(self, primary=None, secondary=..., mode=None, confidence=None, iou_threshold=None,
               latency_budget_ms=None, trigger_classes=None, multi_every=None) -> None:
        with self._lock:
            def check(key):
                if key != "simulated" and key not in self.entries:
                    raise ValueError(f"Unknown model '{key}'")
                if key != "simulated" and self.entries[key].status == "error":
                    raise RuntimeError(f"Model '{key}' is unavailable: {self.entries[key].error}")

            if primary is not None:
                check(primary)
                self.policy.primary = primary
            if secondary is not ...:
                if secondary is not None:
                    check(secondary)
                    if secondary == "simulated":
                        raise ValueError("The simulated detector cannot be a secondary model")
                    if secondary == self.policy.primary:
                        raise ValueError("Secondary model must differ from the primary model")
                self.policy.secondary = secondary
            if mode is not None:
                if mode not in ("single", "cascade", "multi"):
                    raise ValueError(f"Unknown policy mode '{mode}'")
                self.policy.mode = mode
            if confidence is not None:
                self.policy.confidence = float(confidence)
            if iou_threshold is not None:
                self.policy.iou = float(iou_threshold)
            if latency_budget_ms is not None:
                self.policy.latency_budget_ms = float(latency_budget_ms)
            if trigger_classes is not None:
                self.policy.trigger_classes = [normalise_label(c) for c in trigger_classes]
            if multi_every is not None:
                self.policy.multi_every = int(multi_every)
            if self.policy.mode != "single" and not self.policy.secondary:
                self.policy.mode = "single"  # nothing to cascade to
            self.stride, self.secondary_suspended, self.ema_ms = 1, False, None

    # ------------------------------------------------------------ inference
    def _run(self, key: str, frame, frame_id: int, sim_time: float) -> list[dict]:
        entry = self.entries[key]
        started = time.perf_counter()
        try:
            dets = entry.detector.detect(frame, self.policy.confidence, self.policy.iou)
        except Exception as exc:
            entry.status, entry.error = "error", f"{type(exc).__name__}: {exc}"[:160]
            raise
        ms = (time.perf_counter() - started) * 1000
        entry.latencies.append(ms)
        entry.runs += 1
        if entry.status != "loaded":
            entry.status, entry.error = "loaded", None
            info = getattr(entry.detector, "info", None)
            if callable(info):
                meta = info()
                entry.task, entry.classes = meta.get("task"), meta.get("classes")
        for d in dets:
            d.update(model=key, frame_id=frame_id, time=round(sim_time, 3))
        return dets

    def should_process(self) -> bool:
        """Frame-skipping gate driven by the adaptive stride."""
        self.frames_seen += 1
        if (self.frames_seen - 1) % self.stride:
            self.frames_skipped += 1
            return False
        return True

    def infer(self, frame, frame_id: int, sim_time: float) -> tuple[list[dict], dict]:
        """Run the policy on one frame. Raises if the primary model fails."""
        with self._lock:
            p = self.policy
            started = time.perf_counter()
            primary = self._run(p.primary, frame, frame_id, sim_time)
            secondary, reason = [], None
            if p.secondary and p.mode != "single" and not self.secondary_suspended:
                if p.mode == "cascade":
                    lo, hi = p.uncertainty
                    if any(normalise_label(d["label"]) in p.trigger_classes for d in primary):
                        reason = "trigger class detected"
                    elif any(lo <= (d.get("confidence") or 0) < hi for d in primary):
                        reason = "uncertain primary detection"
                elif p.mode == "multi" and frame_id % max(p.multi_every, 1) == 0:
                    reason = f"multi-model frame (every {p.multi_every})"
                if reason:
                    try:
                        secondary = self._run(p.secondary, frame, frame_id, sim_time)
                    except Exception:
                        log.exception("Secondary model %s failed; continuing with primary only", p.secondary)
                        reason = "secondary failed"
            self.last_secondary_reason = reason
            fused = fuse(primary + secondary, p.iou)
            total = (time.perf_counter() - started) * 1000
            self.frames_processed += 1
            self._adapt(total)
            return fused, {"frame_ms": round(total, 1), "secondary_reason": reason}

    def _adapt(self, ms: float) -> None:
        self.ema_ms = ms if self.ema_ms is None else 0.7 * self.ema_ms + 0.3 * ms
        budget = self.policy.latency_budget_ms
        if self.ema_ms > budget:
            if self.policy.secondary and not self.secondary_suspended and self.policy.mode != "single":
                self.secondary_suspended = True
            elif self.stride < MAX_STRIDE:
                self.stride += 1
        elif self.ema_ms < 0.5 * budget:
            if self.stride > 1:
                self.stride -= 1
            elif self.secondary_suspended:
                self.secondary_suspended = False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "ultralytics": self.ultralytics_reason,
                "models": [
                    {"key": "simulated", "kind": "ground_truth", "file": None, "status": "loaded", "error": None,
                     "task": "detect (ground-truth projection, not a model)", "classes": None, "device": "n/a",
                     "runs": None, "latency_ms": None},
                    *[e.to_dict() for e in self.entries.values()],
                ],
                "policy": self.policy.to_dict(),
                "runtime": {
                    "stride": self.stride,
                    "ema_frame_ms": round(self.ema_ms, 1) if self.ema_ms is not None else None,
                    "secondary_suspended": self.secondary_suspended,
                    "last_secondary_reason": self.last_secondary_reason,
                    "frames_processed": self.frames_processed,
                    "frames_skipped": self.frames_skipped,
                },
            }
