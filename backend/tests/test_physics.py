import pytest

from app.config import Settings
from app.simulation.engine import SimulationEngine
from app.simulation.physics import PYBULLET_AVAILABLE, AnalyticCollision
from app.simulation.world import Obstacle

BOX = Obstacle("box", "crate", "rect", 5.0, 5.0, w=1.0, h=1.0, height=1.0)


def test_analytic_clearance_matches_geometry():
    phys = AnalyticCollision(10, 10)
    phys.sync([BOX])
    d, name = phys.clearance(7.0, 5.0)  # 1.5 m from the box surface, minus robot radius
    assert name == "box" and d == pytest.approx(1.2, abs=1e-6)
    d, name = phys.clearance(0.5, 8.0)
    assert name == "boundary" and d == pytest.approx(0.2, abs=1e-6)


@pytest.mark.skipif(not PYBULLET_AVAILABLE, reason="pybullet not installed")
def test_pybullet_clearance_and_contacts():
    from app.simulation.physics import PyBulletCollision

    phys = PyBulletCollision(10, 10)
    try:
        phys.sync([BOX])
        d, name = phys.clearance(7.0, 5.0)
        assert name == "box" and d == pytest.approx(1.2, abs=0.02)
        # Overlapping footprint: negative distance and a reported contact.
        d, name = phys.clearance(5.6, 5.0)
        assert d < 0
        assert phys.contacts() == ["box"]
        # Moving / removing obstacles is mirrored.
        moved = BOX.copy()
        moved.x = 8.0
        phys.sync([moved])
        assert phys.clearance(7.0, 5.0)[0] < 0.3
        phys.sync([])
        assert phys.clearance(7.0, 5.0)[1] == "boundary"
    finally:
        phys.close()


@pytest.mark.skipif(not PYBULLET_AVAILABLE, reason="pybullet not installed")
def test_pybullet_camera_renders_segmentation():
    from app.perception.camera import IMG_H, IMG_W, render_pybullet
    from app.perception.detectors import SimulatedDetector
    from app.simulation.physics import PyBulletCamera

    cam = PyBulletCamera(10, 10)
    try:
        frame = render_pybullet(cam, (2.0, 5.0, 0.0), [BOX], 10, 10)
        assert frame.image.shape == (IMG_H, IMG_W, 3)
        assert frame.renderer == "pybullet"
        assert (frame.seg == 0).any(), "the box straight ahead must be in the mask"
        dets = SimulatedDetector().detect(frame)
        assert dets[0]["label"] == "crate"
        assert dets[0]["distance"] == pytest.approx(2.5, abs=0.4)
    finally:
        cam.close()


def test_engine_reports_physics_backend():
    eng = SimulationEngine(Settings(detector_mode="simulated"))
    try:
        snap = eng.snapshot()
        expected = "pybullet" if PYBULLET_AVAILABLE else "analytic"
        assert snap["safety"]["physics"] == expected
        assert snap["safety"]["in_contact"] is False
    finally:
        eng.shutdown()


def test_analytic_mode_can_be_forced():
    eng = SimulationEngine(Settings(detector_mode="simulated", physics="analytic"))
    assert eng.physics.backend == "analytic"
    assert eng.perception.renderer == "raycast"
    eng.shutdown()
