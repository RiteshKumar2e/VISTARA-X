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


class ObstacleRequest(StrictModel):
    x: float = Field(..., ge=0, le=20)
    y: float = Field(..., ge=0, le=12)
    shape: Literal["rect", "circle"] = "rect"
    size: float = Field(0.8, ge=0.3, le=2.0)
    label: Literal["crate", "barrier", "pallet", "cone"] = "crate"


class DetectorRequest(StrictModel):
    mode: Literal["simulated", "yolov8"]


class PerceptionConfigRequest(StrictModel):
    enabled: Optional[bool] = None
    rate_hz: Optional[float] = Field(None, ge=0.5, le=15)
    confidence: Optional[float] = Field(None, ge=0.05, le=0.95)


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
