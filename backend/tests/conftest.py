import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.simulation.engine import SimulationEngine  # noqa: E402


@pytest.fixture
def settings():
    return Settings(detector_mode="simulated")


@pytest.fixture
def engine(settings):
    """Engine without background threads: tests drive it with step()."""
    return SimulationEngine(settings)


def run_until(engine, statuses, max_seconds=120.0):
    """Step the engine until its status is in `statuses` (sim time, not wall time)."""
    for _ in range(int(max_seconds / engine.dt)):
        engine.step()
        if engine.status in statuses:
            return True
    return False
