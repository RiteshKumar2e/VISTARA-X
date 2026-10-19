"""REST endpoints. Handlers are thin: they validate input and call engine commands."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response

from ..schemas.api import (
    Ack,
    ConfigRequest,
    DetectorRequest,
    ErrorResponse,
    PerceptionConfigRequest,
    NavigateRequest,
    ObstacleRequest,
    Point,
    ResetRequest,
)
from ..simulation.engine import SimulationEngine
from ..simulation.scenarios import SCENARIOS

router = APIRouter()
ERRORS = {409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
STARTED = time.time()


def engine(request: Request) -> SimulationEngine:
    return request.app.state.engine


def _ack(eng: SimulationEngine, message: str) -> Ack:
    return Ack(status=eng.snapshot()["mission"]["status"], message=message)


@router.get("/health", tags=["system"])
def health(request: Request):
    """Service health plus a summary of each subsystem."""
    eng = engine(request)
    p = eng.perception
    sim_ok = eng.thread_alive
    return {
        "status": "ok" if sim_ok else "degraded",
        "service": "vistara-x-backend",
        "subsystems": {
            "simulation": {"ok": sim_ok, "physics": eng.physics.backend},
            "perception": {
                "ok": p.enabled and p.last_error is None,
                "mode": p.mode,
                "renderer": p.renderer,
                "yolo": p.yolo_reason,
            },
            "telemetry": {"ok": True, "clients": request.app.state.hub.client_count},
        },
    }


@router.get("/status", tags=["system"])
def status(request: Request):
    eng = engine(request)
    snap = eng.snapshot()
    perception = snap["perception"]
    return {
        "backend": "ok",
        "uptime_s": round(time.time() - STARTED, 1),
        "simulation": {
            "running": eng.thread_alive,
            "physics": eng.physics.backend,
            "grid_resolution": eng.grid_resolution,
            "rate_hz": eng.settings.sim_hz,
            "scenario": snap["scenario"],
            "sim_time": snap["sim_time"],
        },
        "mission": snap["mission"],
        "perception": {
            "mode": perception["mode"],
            "source_label": perception["source_label"],
            "yolo_available": perception["yolo_available"],
            "yolo_status": perception["yolo_status"],
            "frames": perception["frame_seq"],
            "enabled": perception["enabled"],
            "renderer": perception["renderer"],
            "last_error": perception["last_error"],
        },
        "telemetry": {
            "clients": request.app.state.hub.client_count,
            "rate_hz": eng.settings.telemetry_hz,
        },
    }


@router.get("/scenarios", tags=["simulation"])
def scenarios():
    return {"scenarios": [s.to_dict() for s in SCENARIOS.values()]}


@router.get("/map", tags=["simulation"])
def map_data(request: Request):
    return engine(request).map_data()


@router.get("/path", tags=["navigation"])
def path(request: Request):
    return engine(request).path_data()


@router.get("/telemetry", tags=["simulation"])
def telemetry(request: Request):
    """Same payload as the WebSocket stream, for polling clients and debugging."""
    return engine(request).snapshot()


@router.get("/detections", tags=["perception"])
def detections(request: Request):
    return engine(request).perception.snapshot()


@router.get("/perception/frame", tags=["perception"], responses={204: {"description": "No frame yet"}})
def perception_frame(request: Request):
    jpeg = engine(request).perception.jpeg()
    if jpeg is None:
        return Response(status_code=204)
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/perception/mode", tags=["perception"], response_model=Ack, responses=ERRORS)
def perception_mode(body: DetectorRequest, request: Request):
    eng = engine(request)
    eng.set_detector(body.mode)
    return _ack(eng, f"Detector set to {body.mode}")


@router.post("/perception/config", tags=["perception"], responses=ERRORS)
def perception_config(body: PerceptionConfigRequest, request: Request):
    """Frame-processing controls: enable/disable, processing rate, YOLO confidence."""
    eng = engine(request)
    eng.configure_perception(body.enabled, body.rate_hz, body.confidence)
    snap = eng.perception.snapshot()
    return {
        "ok": True,
        "enabled": snap["enabled"],
        "rate_hz": snap["rate_hz"],
        "confidence_threshold": snap["confidence_threshold"],
    }


@router.post("/target", tags=["navigation"], response_model=Ack, responses=ERRORS)
def set_target(body: Point, request: Request):
    eng = engine(request)
    eng.set_target(body.x, body.y)
    return _ack(eng, f"Target set to ({body.x:.2f}, {body.y:.2f})")


@router.post("/navigate", tags=["navigation"], response_model=Ack, responses=ERRORS)
def navigate(request: Request, body: NavigateRequest | None = None):
    eng = engine(request)
    if body and body.target:
        eng.set_target(body.target.x, body.target.y)
    eng.navigate()
    return _ack(eng, "Mission started")


@router.post("/navigation/pause", tags=["navigation"], response_model=Ack, responses=ERRORS)
def pause(request: Request):
    eng = engine(request)
    eng.pause()
    return _ack(eng, "Mission paused")


@router.post("/navigation/resume", tags=["navigation"], response_model=Ack, responses=ERRORS)
def resume(request: Request):
    eng = engine(request)
    eng.resume()
    return _ack(eng, "Mission resumed")


@router.post("/navigation/stop", tags=["navigation"], response_model=Ack, responses=ERRORS)
def stop(request: Request):
    eng = engine(request)
    eng.stop()
    return _ack(eng, "Mission stopped")


@router.post("/simulation/reset", tags=["simulation"], response_model=Ack, responses=ERRORS)
def reset(request: Request, body: ResetRequest | None = None):
    eng = engine(request)
    scenario = body.scenario if body else "warehouse"
    eng.reset(scenario)
    return _ack(eng, f"Simulation reset to {scenario}")


@router.post("/simulation/config", tags=["simulation"], responses=ERRORS)
def configure(body: ConfigRequest, request: Request):
    eng = engine(request)
    eng.configure(body.max_speed, body.safety_margin, body.moving_obstacles)
    return {"ok": True, "params": eng.snapshot()["params"]}


@router.post("/obstacles", tags=["simulation"], status_code=201, responses=ERRORS)
def add_obstacle(body: ObstacleRequest, request: Request):
    return {"ok": True, "obstacle": engine(request).add_obstacle(body.x, body.y, body.shape, body.size, body.label)}


@router.post("/obstacles/inject", tags=["simulation"], status_code=201, responses=ERRORS)
def inject_obstacle(request: Request):
    """Place a barrier across the active route (used by the guided demo)."""
    return {"ok": True, "obstacle": engine(request).inject_on_route()}


@router.delete("/obstacles", tags=["simulation"])
def clear_obstacles(request: Request):
    return {"ok": True, "removed": engine(request).clear_obstacles()}
