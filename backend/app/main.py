"""VISTARA-X backend entry point.

Run with:  uvicorn app.main:app --reload --port 8000   (from the backend/ folder)
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import routes, websocket
from .config import Settings, settings as default_settings
from .simulation.engine import CommandError, SimulationEngine

logging.basicConfig(
    level=getattr(logging, default_settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("vistara")

RATE_LIMIT = 30  # mutating requests per client IP ...
RATE_WINDOW = 5.0  # ... per this many seconds


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


def _raise_process_priority() -> None:
    """Give the fixed-timestep control loop CPU priority over browsers and editors on
    the same machine (Windows only; opt out with VISTARA_HIGH_PRIORITY=0)."""
    if os.name != "nt" or os.getenv("VISTARA_HIGH_PRIORITY", "1") == "0":
        return
    try:
        import ctypes
        from ctypes import wintypes

        ABOVE_NORMAL_PRIORITY_CLASS = 0x8000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Declare types: the process pseudo-handle is pointer-sized and must not be truncated.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        if kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS):
            log.info("Backend process priority raised to above-normal")
        else:
            log.warning("Could not raise process priority (Windows error %s)", ctypes.get_last_error())
    except Exception as exc:  # pragma: no cover - platform specific
        log.warning("Could not raise process priority: %s", exc)


def create_app(cfg: Settings = default_settings, start_engine: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = SimulationEngine(cfg)
        app.state.engine = engine
        app.state.hub = websocket.TelemetryHub(engine, cfg.telemetry_hz, cfg.max_ws_clients)
        if start_engine:
            _raise_process_priority()
            engine.start()
        app.state.hub.start()
        log.info(
            "VISTARA-X backend ready (env=%s, physics=%s, camera=%s, detector=%s, yolo=%s)",
            cfg.environment,
            engine.physics.backend,
            engine.perception.renderer,
            engine.perception.mode,
            engine.perception.yolo_reason,
        )
        yield
        await app.state.hub.stop()
        engine.shutdown()

    app = FastAPI(
        title="VISTARA-X API",
        version="1.0.0",
        description="Vision-based autonomous navigation simulation API.",
        lifespan=lifespan,
        docs_url=None if cfg.is_production else "/docs",
        redoc_url=None,
    )
    app.state.allowed_origins = set(cfg.cors_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    hits: dict[str, deque] = defaultdict(deque)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in ("POST", "DELETE"):
            ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            q = hits[ip]
            while q and now - q[0] > RATE_WINDOW:
                q.popleft()
            if len(q) >= RATE_LIMIT:
                return _error(429, "rate_limited", "Too many requests; slow down and retry shortly")
            q.append(now)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if cfg.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(CommandError)
    async def command_error(_: Request, exc: CommandError):
        return _error(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return _error(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "internal_error", "Internal server error")

    app.include_router(routes.router)
    app.include_router(websocket.router)
    return app


app = create_app()
