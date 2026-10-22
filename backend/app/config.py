"""Backend settings, loaded from environment variables (and backend/.env if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so we don't need python-dotenv. Existing env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str = field(default_factory=lambda: os.getenv("VISTARA_ENV", "development"))
    cors_origins: list[str] = field(
        default_factory=lambda: _csv(
            "VISTARA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
    )
    # auto | yolo | simulated. "auto" starts in simulated mode and lets the user switch
    # to YOLOv8 at runtime when the model is available.
    detector_mode: str = field(default_factory=lambda: os.getenv("VISTARA_DETECTOR", "simulated"))
    yolo_weights: str = field(
        default_factory=lambda: os.getenv(
            "VISTARA_YOLO_WEIGHTS", str(BACKEND_DIR / "models" / "yolov8n.pt")
        )
    )
    yolo_confidence: float = field(
        default_factory=lambda: float(os.getenv("VISTARA_YOLO_CONFIDENCE", "0.25"))
    )
    sim_hz: float = field(default_factory=lambda: float(os.getenv("VISTARA_SIM_HZ", "20")))
    telemetry_hz: float = field(
        default_factory=lambda: float(os.getenv("VISTARA_TELEMETRY_HZ", "10"))
    )
    perception_hz: float = field(
        default_factory=lambda: float(os.getenv("VISTARA_PERCEPTION_HZ", "4"))
    )
    max_ws_clients: int = field(default_factory=lambda: int(os.getenv("VISTARA_MAX_WS_CLIENTS", "20")))
    # Navigation defaults (speed and margin can also be changed at runtime).
    grid_resolution: float = field(
        default_factory=lambda: float(os.getenv("VISTARA_GRID_RESOLUTION", "0.2"))
    )
    max_speed: float = field(default_factory=lambda: float(os.getenv("VISTARA_MAX_SPEED", "0.9")))
    safety_margin: float = field(
        default_factory=lambda: float(os.getenv("VISTARA_SAFETY_MARGIN", "0.15"))
    )
    # auto | pybullet | analytic. "auto" uses PyBullet when importable.
    physics: str = field(default_factory=lambda: os.getenv("VISTARA_PHYSICS", "auto"))
    # 1 opens the PyBullet GUI window (needs a display); default is headless DIRECT mode.
    pybullet_gui: bool = field(default_factory=lambda: os.getenv("VISTARA_PYBULLET_GUI", "0") == "1")
    log_level: str = field(default_factory=lambda: os.getenv("VISTARA_LOG_LEVEL", "INFO").upper())
    # Saved occupancy maps (ROS map_server PGM + YAML pairs).
    maps_dir: str = field(default_factory=lambda: os.getenv("VISTARA_MAPS_DIR") or str(BACKEND_DIR / "maps"))
    # Speech recognition (faster-whisper). tiny | base | small | medium. "base" answers in
    # ~3-6 s on a 4-core laptop CPU; "small" is more accurate for Hindi but ~4x slower.
    whisper_model: str = field(default_factory=lambda: os.getenv("VISTARA_WHISPER_MODEL") or "base")
    # Delivery log (JSON lines) and optional webhook that receives every notification
    # (connect it to an SMS, WhatsApp or chat gateway). Empty = no external messages.
    ops_dir: str = field(default_factory=lambda: os.getenv("VISTARA_OPS_DIR") or str(BACKEND_DIR / "operations"))
    webhook_url: str = field(default_factory=lambda: os.getenv("VISTARA_WEBHOOK_URL", ""))
    # Optional access keys. When set, changing anything requires X-API-Key: operator or
    # admin key; viewing never does. Admin-only: resets, parameters, map import, operations settings.
    operator_key: str = field(default_factory=lambda: os.getenv("VISTARA_OPERATOR_KEY", ""))
    admin_key: str = field(default_factory=lambda: os.getenv("VISTARA_ADMIN_KEY", ""))

    def __post_init__(self) -> None:
        if not 0.05 <= self.grid_resolution <= 1.0:
            raise ValueError("VISTARA_GRID_RESOLUTION must be between 0.05 and 1.0 metres")
        if not 1 <= self.sim_hz <= 200:
            raise ValueError("VISTARA_SIM_HZ must be between 1 and 200")
        # Relative weight paths are resolved against the backend/ folder.
        path = Path(self.yolo_weights)
        if not path.is_absolute():
            object.__setattr__(self, "yolo_weights", str(BACKEND_DIR / path))

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
