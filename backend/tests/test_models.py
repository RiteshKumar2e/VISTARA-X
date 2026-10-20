import time

import pytest

from app.perception.registry import ModelRegistry, fuse, iou


class FakeDetector:
    """In-process stand-in for a YOLO model: returns fixed boxes, can fail or be slow."""

    def __init__(self, dets, fail=False, delay=0.0, task="detect"):
        self.dets, self.fail, self.delay, self.task = dets, fail, delay, task
        self.calls = 0

    def detect(self, frame, conf=None, iou=None):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("weights corrupted")
        return [dict(d) for d in self.dets if (d.get("confidence") or 0) >= (conf or 0)]

    def info(self):
        return {"task": self.task, "classes": 80}


def det(label, conf, bbox):
    return {"label": label, "confidence": conf, "bbox": bbox, "distance": None, "bearing_deg": 0.0, "source": "yolov8"}


@pytest.fixture
def reg(tmp_path):
    return ModelRegistry(tmp_path)  # empty models dir: only registered fakes


def test_discovery_handles_missing_weights(tmp_path):
    r = ModelRegistry(tmp_path, [str(tmp_path / "nope.pt")])
    assert r.real_models() == []
    snap = r.snapshot()
    assert snap["models"][0]["key"] == "simulated"
    assert snap["policy"]["primary"] == "simulated"


def test_discovers_weight_files(tmp_path):
    (tmp_path / "yolov8s.pt").write_bytes(b"not really weights")
    r = ModelRegistry(tmp_path)
    assert "yolov8s" in r.entries
    assert r.snapshot()["models"][1]["file"] == "yolov8s.pt"


def test_iou_and_fusion_policy():
    assert iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    a = {**det("person", 0.6, [10, 10, 50, 90]), "model": "m1"}
    b = {**det("Person", 0.8, [12, 12, 52, 88]), "model": "m2"}
    c = {**det("car", 0.7, [12, 12, 52, 88]), "model": "m2"}  # same box, other class: kept
    out = fuse([a, b, c], 0.5)
    people = [d for d in out if d["label"] == "person"]
    assert len(out) == 2 and len(people) == 1
    assert people[0]["models"] == ["m2", "m1"] and people[0]["agreement"] is True
    assert people[0]["confidence"] == 0.8  # max, not boosted by the second model


def test_select_validation(reg):
    reg.register("a", FakeDetector([]))
    reg.register("b", FakeDetector([]))
    with pytest.raises(ValueError):
        reg.select(primary="missing")
    with pytest.raises(ValueError):
        reg.select(primary="a", secondary="a")
    with pytest.raises(ValueError):
        reg.select(primary="a", secondary="simulated")
    with pytest.raises(ValueError):
        reg.select(mode="everything")
    reg.select(primary="a", secondary="b", mode="cascade", confidence=0.3, iou_threshold=0.6)
    assert reg.policy.mode == "cascade" and reg.policy.iou == 0.6
    reg.select(secondary=None)
    reg.select(mode="cascade")
    assert reg.policy.mode == "single"  # cannot cascade without a secondary model


def test_cascade_runs_secondary_only_when_triggered(reg):
    prim = FakeDetector([det("chair", 0.9, [0, 0, 10, 10])])
    sec = FakeDetector([det("person", 0.7, [50, 50, 60, 90])])
    reg.register("p", prim)
    reg.register("s", sec)
    reg.select(primary="p", secondary="s", mode="cascade", trigger_classes=["person"], latency_budget_ms=10_000)
    out, meta = reg.infer(None, 1, 0.0)
    assert sec.calls == 0 and meta["secondary_reason"] is None
    assert out[0]["model"] == "p" and out[0]["frame_id"] == 1
    prim.dets = [det("person", 0.9, [50, 50, 60, 90])]
    out, meta = reg.infer(None, 2, 0.1)
    assert sec.calls == 1 and meta["secondary_reason"] == "trigger class detected"
    assert out[0]["models"] == ["p", "s"] and out[0]["agreement"]
    prim.dets = [det("chair", 0.3, [0, 0, 10, 10])]  # inside the uncertainty band
    _, meta = reg.infer(None, 3, 0.2)
    assert meta["secondary_reason"] == "uncertain primary detection"


def test_multi_mode_every_nth_frame(reg):
    reg.register("p", FakeDetector([]))
    sec = FakeDetector([])
    reg.register("s", sec)
    reg.select(primary="p", secondary="s", mode="multi", multi_every=3, latency_budget_ms=10_000)
    for f in range(1, 10):
        reg.infer(None, f, 0.0)
    assert sec.calls == 3  # frames 3, 6, 9


def test_model_failure_is_reported(reg):
    reg.register("bad", FakeDetector([], fail=True))
    reg.select(primary="bad")
    with pytest.raises(RuntimeError):
        reg.infer(None, 1, 0.0)
    entry = reg.snapshot()["models"][1]
    assert entry["status"] == "error" and "weights corrupted" in entry["error"]
    with pytest.raises(RuntimeError):
        reg.select(primary="bad")  # cannot select a failed model again


def test_secondary_failure_keeps_primary_results(reg):
    reg.register("p", FakeDetector([det("person", 0.9, [0, 0, 10, 10])]))
    reg.register("s", FakeDetector([], fail=True))
    reg.select(primary="p", secondary="s", mode="cascade", latency_budget_ms=10_000)
    out, meta = reg.infer(None, 1, 0.0)
    assert len(out) == 1 and meta["secondary_reason"] == "secondary failed"


def test_latency_budget_adapts_stride_and_suspends_secondary(reg):
    reg.register("p", FakeDetector([det("person", 0.9, [0, 0, 10, 10])], delay=0.03))
    reg.register("s", FakeDetector([], delay=0.03))
    reg.select(primary="p", secondary="s", mode="cascade", latency_budget_ms=20)
    reg.infer(None, 1, 0.0)
    assert reg.secondary_suspended  # first step: drop the optional model
    reg.infer(None, 2, 0.0)
    assert reg.stride == 2  # still over budget: process fewer frames
    processed = sum(reg.should_process() for _ in range(10))
    assert processed == 5 and reg.frames_skipped == 5
    rt = reg.snapshot()["runtime"]
    assert rt["frames_skipped"] == 5 and rt["ema_frame_ms"] > 20
    lat = reg.snapshot()["models"][1]["latency_ms"]
    assert lat["samples"] == 2 and lat["mean"] >= 25
