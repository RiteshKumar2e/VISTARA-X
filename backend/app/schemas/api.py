"""Request / response schemas. Telemetry is a free-form dict documented in the README;
inputs are strictly validated here."""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(StrictModel):
    x: float = Field(..., ge=0, le=20, description="metres from the left edge")
    y: float = Field(..., ge=0, le=12, description="metres from the bottom edge")

    @field_validator("x", "y")
    @classmethod
    def finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be a finite number")
        return v


class NavigateRequest(StrictModel):
    target: Optional[Point] = None


class ResetRequest(StrictModel):
    scenario: str = Field("warehouse", min_length=1, max_length=32, pattern=r"^[a-z_]+$")


class ConfigRequest(StrictModel):
    max_speed: Optional[float] = Field(None, ge=0.2, le=1.5)
    safety_margin: Optional[float] = Field(None, ge=0.05, le=0.6)
    moving_obstacles: Optional[bool] = None
    # Predictive avoidance on (default) or off (the reactive baseline).
    predictive: Optional[bool] = None


class ObstacleRequest(StrictModel):
    x: float = Field(..., ge=0, le=20)
    y: float = Field(..., ge=0, le=12)
    shape: Literal["rect", "circle"] = "rect"
    size: float = Field(0.8, ge=0.3, le=2.0)
    label: Literal["crate", "barrier", "pallet", "cone", "person"] = "crate"
    # Person only: walk back and forth between (x, y) and this point at walking pace.
    patrol_to: Optional[Point] = None


class DetectorRequest(StrictModel):
    mode: Literal["simulated", "yolov8"]


class PerceptionConfigRequest(StrictModel):
    enabled: Optional[bool] = None
    rate_hz: Optional[float] = Field(None, ge=0.5, le=15)
    confidence: Optional[float] = Field(None, ge=0.05, le=0.95)


SensorKey = Literal["lidar", "ultrasonic", "imu", "odometry", "camera", "safety"]


class SensorConfigRequest(StrictModel):
    sensor: SensorKey
    enabled: Optional[bool] = None
    rate_hz: Optional[float] = Field(None, ge=0.5, le=50)
    params: Optional[dict[str, float]] = None


class ModelSelectRequest(StrictModel):
    primary: Optional[str] = Field(None, min_length=1, max_length=64)
    secondary: Optional[str] = Field(None, max_length=64)
    clear_secondary: bool = False
    mode: Optional[Literal["single", "cascade", "multi"]] = None
    confidence: Optional[float] = Field(None, ge=0.05, le=0.95)
    iou: Optional[float] = Field(None, ge=0.1, le=0.95)
    latency_budget_ms: Optional[float] = Field(None, ge=20, le=5000)
    trigger_classes: Optional[list[str]] = Field(None, max_length=20)
    multi_every: Optional[int] = Field(None, ge=1, le=30)


class CommandRequest(StrictModel):
    text: str = Field(..., max_length=300, description="Transcript or typed command (English or Hindi)")
    source: Literal["text", "speech", "browser_speech", "selector"] = "text"
    # Execute a valid destination without asking for confirmation.
    trusted: bool = False
    # Speech-recognition metadata to keep with the transcript (from /speech/transcribe or the browser).
    speech: Optional[dict[str, Optional[str | float | bool]]] = None


class MapNameRequest(StrictModel):
    name: str = Field(..., min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")


class MapImportRequest(StrictModel):
    name: str = Field(..., min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    yaml: str = Field(..., min_length=10, max_length=4000, description="map_server YAML text")
    pgm_base64: str = Field(..., min_length=8, max_length=8_000_000, description="PGM image, base64-encoded")


class PlannerMapRequest(StrictModel):
    source: Literal["simulator", "slam", "imported"]


class MappingControlRequest(StrictModel):
    enabled: Optional[bool] = None
    clear: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[list] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Ack(BaseModel):
    ok: bool = True
    status: str
    message: str
