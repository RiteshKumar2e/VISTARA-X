"""Scene understanding: turn per-frame detections into mission-relevant facts."""

from __future__ import annotations

from collections import Counter

from .classes import policy_for

AHEAD_BEARING = 25.0  # degrees either side of the optical axis
SLOW_FACTOR = 0.5


def summarise(detections: list[dict]) -> dict:
    counts = Counter(d["label"] for d in detections)
    relevant = [d for d in detections if policy_for(d["label"]).obstacle]
    ranged = [d for d in relevant if d.get("distance") is not None]
    nearest = min(ranged, key=lambda d: d["distance"]) if ranged else None
    slow_for = [
        d["label"]
        for d in ranged
        if policy_for(d["label"]).slow_radius > 0
        and d["distance"] < policy_for(d["label"]).slow_radius
        and abs(d.get("bearing_deg", 0.0)) < AHEAD_BEARING
    ]
    return {
        "object_counts": dict(counts),
        "relevant_count": len(relevant),
        "ignored_count": len(detections) - len(relevant),
        "nearest": (
            {
                "label": nearest["label"],
                "distance": nearest["distance"],
                "bearing_deg": nearest["bearing_deg"],
            }
            if nearest
            else None
        ),
        "person_ahead": "person" in slow_for,
        # Speed governor applied by the controller (1.0 = no restriction).
        "speed_factor": SLOW_FACTOR if slow_for else 1.0,
    }
