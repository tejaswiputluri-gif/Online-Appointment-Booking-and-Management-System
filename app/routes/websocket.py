"""
WebSocket endpoint for live doctor schedule updates.

Client connects to:  ws://host/ws/doctors/{doctor_id}/slots
Receives JSON events like:
  {"event": "slot_booked", "slot_id": 12, "doctor_id": 1, ...}
  {"event": "slot_freed",  "slot_id": 12, "doctor_id": 1, ...}
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws/doctors/{doctor_id}/slots")
async def doctor_slots_ws(websocket: WebSocket, doctor_id: int) -> None:
    await ws_manager.connect(doctor_id, websocket)
    try:
        # Keep the connection alive; clients may send pings/text we ignore
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(doctor_id, websocket)
    except Exception as exc:
        logger.warning("WebSocket error doctor_id=%s: %s", doctor_id, exc)
        await ws_manager.disconnect(doctor_id, websocket)
