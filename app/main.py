"""
FastAPI application entrypoint.

Run locally:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

AWS (EC2) sketch:
  - RDS PostgreSQL for DATABASE_URL
  - ElastiCache Redis for REDIS_URL
  - systemd or Docker on EC2 running uvicorn with multiple workers
  - ALB in front; enable sticky sessions only if you skip Redis Pub/Sub for WS
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import init_db
from app.redis_client.client import redis_ping
from app.routes import appointments, auth, doctors, websocket
from app.services.reminders import start_scheduler, stop_scheduler
from app.websocket.manager import start_slot_event_subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    logger.info("Starting %s (%s)", settings.app_name, settings.app_env)
    init_db()
    if redis_ping():
        logger.info("Redis connection OK")
    else:
        logger.warning(
            "Redis not reachable at %s — locks/cache/rate-limits will fail until it is up",
            settings.redis_url,
        )

    start_scheduler()
    subscriber_task = asyncio.create_task(start_slot_event_subscriber())

    yield

    # --- shutdown ---
    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass
    stop_scheduler()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Real-Time Appointment/Booking System with Redis distributed locking, "
        "JWT RBAC, WebSocket live updates, and APScheduler reminders."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(doctors.router)
app.include_router(appointments.router)
app.include_router(websocket.router)


@app.get("/", include_in_schema=False)
def root():
    """Render/browsers hit / by default — send them to Swagger docs."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/docs")


@app.get("/health", tags=["Ops"])
def health() -> dict:
    """Lightweight health check for ALB / ECS / Kubernetes probes."""
    return {
        "status": "ok",
        "redis": redis_ping(),
        "env": settings.app_env,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler so clients never see raw stack traces in production."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    if settings.debug:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "type": type(exc).__name__},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
