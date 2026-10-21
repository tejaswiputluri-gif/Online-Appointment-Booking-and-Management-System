"""API routers package."""

from app.routes import appointments, auth, doctors, websocket

__all__ = ["auth", "doctors", "appointments", "websocket"]
