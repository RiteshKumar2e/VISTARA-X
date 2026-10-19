"""Telemetry hub: one broadcaster task samples the engine at a fixed rate and pushes
the latest snapshot to each client through a bounded queue (size 1, newest wins),
so a slow client never builds up stale messages or slows down the others."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..simulation.engine import TELEMETRY_VERSION

log = logging.getLogger("vistara.ws")
router = APIRouter()


class TelemetryHub:
    def __init__(self, engine, rate_hz: float, max_clients: int):
        self.engine = engine
        self.period = 1.0 / rate_hz
        self.max_clients = max_clients
        self._clients: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def start(self) -> None:
        self._task = asyncio.create_task(self._broadcast())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def register(self) -> asyncio.Queue | None:
        if len(self._clients) >= self.max_clients:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._clients.add(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    async def _broadcast(self) -> None:
        last_seq = None
        while True:
            await asyncio.sleep(self.period)
            if not self._clients:
                continue
            snap = await asyncio.to_thread(self.engine.snapshot)
            if snap["seq"] == last_seq:
                continue
            last_seq = snap["seq"]
            message = json.dumps(snap, separators=(",", ":"))
            for q in list(self._clients):
                if q.full():
                    try:
                        q.get_nowait()  # drop the stale frame
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(message)


@router.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    hub: TelemetryHub = websocket.app.state.hub
    origin = websocket.headers.get("origin")
    allowed = websocket.app.state.allowed_origins
    if origin and allowed and origin not in allowed:
        await websocket.close(code=1008)
        return
    queue = hub.register()
    if queue is None:
        await websocket.close(code=1013)  # try again later
        return
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(text: str) -> None:
        async with send_lock:  # one writer at a time
            await websocket.send_text(text)

    # Send an immediate snapshot so the client renders without waiting a tick.
    await send(json.dumps(await asyncio.to_thread(hub.engine.snapshot)))

    async def sender():
        while True:
            await send(await queue.get())

    async def receiver():
        # Commands go through REST; the socket only accepts {"type": "ping"}.
        # Anything else gets a structured error instead of being silently dropped.
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text) if len(text) <= 1024 else None
            except ValueError:
                msg = None
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await send(json.dumps({"type": "pong", "version": TELEMETRY_VERSION}))
            else:
                await send(json.dumps({
                    "type": "error",
                    "version": TELEMETRY_VERSION,
                    "code": "invalid_message",
                    "message": 'Only {"type": "ping"} is accepted; use the REST API for commands.',
                }))

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.info("Telemetry client closed: %s", type(exc).__name__)
    finally:
        for t in tasks:
            t.cancel()
        hub.unregister(queue)
