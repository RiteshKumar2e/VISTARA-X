"""Which detected classes matter for navigation, and how.

Not every detection is an obstacle: a "tv" or "clock" seen by a COCO model is
ignored, a "person" is a moving obstacle that also triggers the speed governor.
Edit CLASS_POLICY to change the mapping; unknown classes default to IGNORE.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassPolicy:
    obstacle: bool  # should it be tracked as a navigation-relevant obstacle?
    dynamic: bool = False  # expected to move
    slow_radius: float = 0.0  # reduce speed when closer than this (metres), 0 = never
    footprint: float = 0.5  # assumed radius (m) for a camera-derived track


_STATIC = ClassPolicy(obstacle=True)
_DYNAMIC = ClassPolicy(obstacle=True, dynamic=True, footprint=0.4)

CLASS_POLICY: dict[str, ClassPolicy] = {
    # Simulation classes (ground-truth detector).
    "shelf": _STATIC,
    "pallet": _STATIC,
    "barrier": _STATIC,
    "cone": ClassPolicy(obstacle=True, footprint=0.3),
    "crate": _STATIC,
    "person": ClassPolicy(obstacle=True, dynamic=True, slow_radius=2.5, footprint=0.35),
    # COCO classes that YOLOv8 may report.
    "bicycle": _DYNAMIC,
    "car": _DYNAMIC,
    "motorcycle": _DYNAMIC,
    "truck": _DYNAMIC,
    "dog": _DYNAMIC,
    "cat": _DYNAMIC,
    "chair": _STATIC,
    "bench": _STATIC,
    "couch": _STATIC,
    "dining table": _STATIC,
    "potted plant": _STATIC,
    "suitcase": _STATIC,
    "refrigerator": _STATIC,
}

IGNORE = ClassPolicy(obstacle=False)


def policy_for(label: str) -> ClassPolicy:
    return CLASS_POLICY.get(label, IGNORE)
