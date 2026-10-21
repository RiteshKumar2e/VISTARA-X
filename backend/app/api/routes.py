"""REST endpoints. Handlers are thin: they validate input and call engine commands."""

from __future__ import annotations

import base64
import binascii
import time

from fastapi import APIRouter, Query, Request, Response

from ..schemas.api import (
    Ack,
    CommandRequest,
    ConfigRequest,
    MapImportRequest,
    MapNameRequest,
    MappingControlRequest,
    PlannerMapRequest,
    DetectorRequest,
    ErrorResponse,
    ModelSelectRequest,
    PerceptionConfigRequest,
    SensorConfigRequest,
    NavigateRequest,
    ObstacleRequest,
    Point,
    ResetRequest,
)
from ..simulation.engine import CommandError, SimulationEngine
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
        "planner": {
            "algorithm": "A* (8-connected, octile heuristic)",
            "last_plan": snap["last_plan"],
            "ready": eng.thread_alive,
        },
        "controller": {
            "type": "pure pursuit",
            "active": snap["mission"]["status"] in ("planning", "navigating"),
            "ready": eng.thread_alive,
            "params": snap["params"],
        },
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


@router.post("/navigation/estop", tags=["navigation"], response_model=Ack)
def emergency_stop(request: Request):
    """Emergency stop: always succeeds and halts the robot, with or without a mission."""
    eng = engine(request)
    return _ack(eng, eng.emergency_stop())


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
    return {"ok": True, "obstacle": engine(request).add_obstacle(
        body.x, body.y, body.shape, body.size, body.label,
        patrol_to=(body.patrol_to.x, body.patrol_to.y) if body.patrol_to else None,
    )}


@router.post("/obstacles/{obstacle_id}/move", tags=["simulation"], responses=ERRORS)
def move_obstacle(obstacle_id: str, body: Point, request: Request):
    """Move an obstacle you added (scenario obstacles are fixed)."""
    if len(obstacle_id) > 32:
        raise CommandError("not_found", "No such obstacle", 404)
    return {"ok": True, "obstacle": engine(request).move_obstacle(obstacle_id, body.x, body.y)}


@router.post("/simulation/obstacles", tags=["simulation"], status_code=201, responses=ERRORS)
def add_simulation_obstacle(body: ObstacleRequest, request: Request):
    """Add an obstacle (same as POST /obstacles)."""
    return {"ok": True, "obstacle": engine(request).add_obstacle(
        body.x, body.y, body.shape, body.size, body.label,
        patrol_to=(body.patrol_to.x, body.patrol_to.y) if body.patrol_to else None,
    )}


@router.delete("/simulation/obstacles/{obstacle_id}", tags=["simulation"], responses=ERRORS)
def remove_obstacle(obstacle_id: str, request: Request):
    """Remove one obstacle you added (scenario obstacles are fixed)."""
    if len(obstacle_id) > 32:
        raise CommandError("not_found", "No such obstacle", 404)
    engine(request).remove_obstacle(obstacle_id)
    return {"ok": True, "removed": obstacle_id}


@router.get("/sensors", tags=["sensors"])
def sensors(request: Request):
    """Every sensor (all simulated) with health, rate, data age and latest reading."""
    return engine(request).sensor_status()


@router.post("/sensors/configure", tags=["sensors"], responses=ERRORS)
def configure_sensor(body: SensorConfigRequest, request: Request):
    return {"ok": True, "sensor": engine(request).configure_sensor(body.sensor, body.enabled, body.rate_hz, body.params)}


@router.get("/models", tags=["perception"])
def models(request: Request):
    """Detector registry: discovered weights, load state, latency and execution policy."""
    registry = engine(request).perception.registry
    registry.rescan()
    return registry.snapshot()


@router.post("/models/select", tags=["perception"], responses=ERRORS)
def select_models(body: ModelSelectRequest, request: Request):
    kwargs = body.model_dump(exclude_none=True, exclude={"clear_secondary", "iou"})
    if body.iou is not None:
        kwargs["iou_threshold"] = body.iou
    if body.clear_secondary:
        kwargs["secondary"] = None
    return {"ok": True, **engine(request).select_models(**kwargs)}


@router.post("/obstacles/inject", tags=["simulation"], status_code=201, responses=ERRORS)
def inject_obstacle(request: Request):
    """Place a barrier across the active route (used by the guided demo)."""
    return {"ok": True, "obstacle": engine(request).inject_on_route()}


@router.delete("/obstacles", tags=["simulation"])
def clear_obstacles(request: Request):
    return {"ok": True, "removed": engine(request).clear_obstacles()}


# ================================================================ mapping and localisation
@router.get("/mapping", tags=["mapping"], responses=ERRORS)
def mapping(request: Request, which: str = Query("slam", pattern="^(slam|imported)$")):
    """The live SLAM map (or the imported map) with pose estimate, trajectory, last scan
    and localisation status. All data is simulation-generated."""
    return engine(request).mapping_data(which)


@router.post("/mapping/explore", tags=["mapping"], response_model=Ack, responses=ERRORS)
def explore(request: Request):
    """Autonomous frontier exploration: the robot maps the area by itself."""
    eng = engine(request)
    eng.explore()
    return _ack(eng, "Exploration started")


@router.post("/mapping/control", tags=["mapping"], responses=ERRORS)
def mapping_control(body: MappingControlRequest, request: Request):
    eng = engine(request)
    eng.set_mapping(body.enabled, body.clear)
    return {"ok": True, "mapping": eng.mapping_status()}


@router.post("/mapping/planner", tags=["mapping"], responses=ERRORS)
def planner_map(body: PlannerMapRequest, request: Request):
    """Which map the A* planner uses: simulator geometry, the live SLAM map or the imported map."""
    eng = engine(request)
    eng.set_planner_map(body.source)
    return {"ok": True, "mapping": eng.mapping_status()}


@router.get("/mapping/export", tags=["mapping"])
def export_map(request: Request, file: str = Query("pgm", pattern="^(pgm|yaml)$")):
    """The live SLAM map in ROS map_server format (download map.pgm and map.yaml)."""
    pgm, yaml = engine(request).export_map()
    if file == "pgm":
        return Response(pgm, media_type="image/x-portable-graymap",
                        headers={"Content-Disposition": 'attachment; filename="map.pgm"'})
    return Response(yaml, media_type="text/yaml", headers={"Content-Disposition": 'attachment; filename="map.yaml"'})


@router.get("/mapping/maps", tags=["mapping"])
def saved_maps(request: Request):
    return {"maps": engine(request).list_maps()}


@router.post("/mapping/save", tags=["mapping"], responses=ERRORS)
def save_map(body: MapNameRequest, request: Request):
    return {"ok": True, "map": engine(request).save_map(body.name)}


@router.post("/mapping/load", tags=["mapping"], responses=ERRORS)
def load_map(body: MapNameRequest, request: Request):
    """Load a saved map as the imported map (select it with /mapping/planner to plan on it)."""
    return {"ok": True, "map": engine(request).load_map(body.name)}


@router.post("/mapping/import", tags=["mapping"], responses=ERRORS)
def import_map(body: MapImportRequest, request: Request):
    """Import a ROS map_server map: YAML text plus the PGM image (base64)."""
    try:
        pgm = base64.b64decode(body.pgm_base64, validate=True)
    except (binascii.Error, ValueError):
        raise CommandError("invalid_map", "pgm_base64 is not valid base64", 422)
    return {"ok": True, "map": engine(request).import_map(body.yaml, pgm, body.name)}


# ================================================================ places, commands, speech
@router.get("/places", tags=["commands"])
def places(request: Request):
    """Named destinations of the current scenario (with their Hindi names and aliases)."""
    eng = engine(request)
    return {"scenario": eng.scenario.key, "places": [p.to_dict() for p in eng.scenario.places]}


@router.post("/commands/interpret", tags=["commands"], responses=ERRORS)
def interpret(body: CommandRequest, request: Request):
    """Parse a typed or recognised command, validate it and (for stop/pause/resume, or in
    trusted mode) execute it. New destinations otherwise wait for /commands/{id}/confirm."""
    return request.app.state.commands.interpret(body.text, body.source, body.speech, body.trusted)


@router.post("/commands/{command_id}/confirm", tags=["commands"], responses=ERRORS)
def confirm_command(command_id: int, request: Request):
    return request.app.state.commands.confirm(command_id)


@router.post("/commands/{command_id}/cancel", tags=["commands"], responses=ERRORS)
def cancel_command(command_id: int, request: Request):
    return request.app.state.commands.cancel(command_id)


@router.get("/commands", tags=["commands"])
def command_history(request: Request):
    """Every command this session: transcript, language, intent, validation and response."""
    return {"commands": request.app.state.commands.snapshot()}


@router.get("/speech/status", tags=["commands"])
def speech_status(request: Request):
    return request.app.state.speech.status()


@router.post("/speech/load", tags=["commands"], responses=ERRORS)
def speech_load(request: Request):
    """Load the Whisper model now, so the first command is not delayed by loading."""
    return request.app.state.speech.warm_up()


@router.post("/speech/transcribe", tags=["commands"], responses=ERRORS)
async def speech_transcribe(request: Request, language: str | None = Query(None, pattern="^(en|hi)$")):
    """Transcribe a short recording (raw request body: audio/webm, audio/ogg or audio/wav)
    with local Whisper. Returns the text, language and confidence information."""
    ctype = request.headers.get("content-type", "").split(";")[0].strip()
    if not ctype.startswith("audio/") and ctype != "application/octet-stream":
        raise CommandError("bad_audio", "Send the recording as audio/webm, audio/ogg or audio/wav", 415)
    if int(request.headers.get("content-length") or 0) > 3 * 1024 * 1024:
        raise CommandError("audio_too_large", "Audio clip is larger than 3 MB", 413)
    data = await request.body()
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(request.app.state.speech.transcribe, data, language)
