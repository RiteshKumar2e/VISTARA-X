import pytest

from app.perception.camera import IMG_H, IMG_W, render
from app.perception.detectors import SimulatedDetector, YoloDetector
from app.scene.understanding import summarise
from app.simulation.scenarios import SCENARIOS


def frame_for(key):
    w = SCENARIOS[key].build()
    return render((w.robot.x, w.robot.y, w.robot.theta), w.obstacles, w.width, w.height)


def test_camera_frame_shapes():
    frame = frame_for("warehouse")
    assert frame.image.shape == (IMG_H, IMG_W, 3)
    assert frame.depth.shape == (IMG_W,)
    assert (frame.depth > 0).all()


def test_simulated_detector_is_labelled_ground_truth():
    dets = SimulatedDetector().detect(frame_for("enclosed"))
    assert dets, "shelves and barriers ahead should be visible"
    for d in dets:
        assert d["source"] == "ground_truth"
        assert d["confidence"] is None  # no fabricated confidence
        x1, y1, x2, y2 = d["bbox"]
        assert 0 <= x1 < x2 <= IMG_W and 0 <= y1 < y2 <= IMG_H
    assert {"shelf", "barrier"} & {d["label"] for d in dets}


def test_scene_speed_governor():
    near = [{"label": "person", "distance": 1.2, "bearing_deg": 3.0}]
    far = [{"label": "person", "distance": 6.0, "bearing_deg": 3.0}]
    assert summarise(near)["speed_factor"] == 0.5
    assert summarise(far)["speed_factor"] == 1.0
    assert summarise([])["nearest"] is None


def test_yolo_unavailable_without_weights(tmp_path):
    ok, reason = YoloDetector.availability(str(tmp_path / "missing.pt"))
    assert not ok and "not found" in reason


@pytest.mark.yolo
def test_yolo_runs_real_inference(settings):
    ok, reason = YoloDetector.availability(settings.yolo_weights)
    if not ok:
        pytest.skip(f"YOLOv8 unavailable: {reason}")
    dets = YoloDetector(settings.yolo_weights).detect(frame_for("warehouse"))
    assert isinstance(dets, list)
    for d in dets:
        assert d["source"] == "yolov8"
        assert 0 <= d["confidence"] <= 1
