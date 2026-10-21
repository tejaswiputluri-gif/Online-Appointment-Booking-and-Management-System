"""
In-memory WebSocket connection manager, keyed by doctor_id.

================================================================================
WHY WEBSOCKETS INSTEAD OF POLLING?
================================================================================
Polling GET /doctors/{id}/slots every few seconds:
  - Wastes bandwidth and DB/Redis load when nothing changes
  - Adds latency equal to the poll interval
  - Multiplies with open browser tabs × doctors viewed

WebSockets push an event the instant a slot is booked/cancelled:
  - Near real-time UI updates
  - One persistent connection per viewer
  - Server only sends when state changes

Trade-off: connections are sticky to a process. On multiple EC2 instances you
need a pub/sub bridge (Redis Pub/Sub / SNS) so instance A can notify viewers
connected to instance B. This project includes Redis Pub/Sub fan-out for that
exact multi-server case — see broadcast_slot_event().
================================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track live WebSocket clients subscribed to a doctor's schedule."""

    def __init__(self) -> None:
        # doctor_id → set of WebSocket connections on THIS process
        self._rooms: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, doctor_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._rooms.setdefault(doctor_id, set()).add(websocket)
        logger.info("WS connected doctor_id=%s (room size=%s)", doctor_id, len(self._rooms[doctor_id]))

    async def disconnect(self, doctor_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(doctor_id)
            if not room:
                return
            room.discard(websocket)
            if not room:
                self._rooms.pop(doctor_id, None)
        logger.info("WS disconnected doctor_id=%s", doctor_id)

    async def local_broadcast(self, doctor_id: int, message: dict[str, Any]) -> None:
        """Send to sockets connected to this worker only."""
        payload = json.dumps(message, default=str)
        async with self._lock:
            sockets = list(self._rooms.get(doctor_id, set()))
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(doctor_id, ws)


# Process-wide singleton used by routes + booking service
ws_manager = ConnectionManager()


# Redis channel for cross-instance fan-out
SLOT_EVENTS_CHANNEL = "slot_events"


def publish_slot_event(doctor_id: int, event: dict[str, Any]) -> None:
    """
    Publish to Redis Pub/Sub so EVERY app instance can notify its local sockets.

    Multi-server path:
      EC2-A books slot → publish → EC2-B subscriber → local_broadcast to its WS clients
    """
    from app.redis_client.client import get_redis

    payload = {"doctor_id": doctor_id, **event}
    try:
        get_redis().publish(SLOT_EVENTS_CHANNEL, json.dumps(payload, default=str))
    except Exception as exc:
        logger.warning("Redis publish failed (falling back to local only): %s", exc)
        # Best-effort local notify even if Redis pub/sub fails
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.local_broadcast(doctor_id, payload))
        except RuntimeError:
            pass


async def start_slot_event_subscriber() -> None:
    """
    Background task: subscribe to Redis and fan-in to local WebSockets.

    Started from FastAPI lifespan in main.py.
    """
    from app.redis_client.client import get_redis

    pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(SLOT_EVENTS_CHANNEL)
    logger.info("Subscribed to Redis channel %s", SLOT_EVENTS_CHANNEL)

    try:
        while True:
            # redis-py pubsub is blocking; poll in a thread-friendly way
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            if message and message.get("type") == "message":
                try:
                    data = json.loads(message["data"])
                    doctor_id = int(data.pop("doctor_id"))
                    await ws_manager.local_broadcast(doctor_id, data)
                except Exception as exc:
                    logger.warning("Bad slot event payload: %s", exc)
            else:
                await asyncio.sleep(0.05)
    finally:
        try:
            pubsub.unsubscribe(SLOT_EVENTS_CHANNEL)
            pubsub.close()
        except Exception:
            pass
