"""
Redis cache helpers for available slots.

Interview note:
- Cache key: slots:doctor:{doctor_id}:available
- Invalidate on book AND cancel so list endpoints stay consistent.
- Short TTL as a safety net if invalidation is missed.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import redis

from app.redis_client.client import get_redis

SLOTS_CACHE_TTL_SECONDS = 60


def _key(doctor_id: int) -> str:
    return f"slots:doctor:{doctor_id}:available"


def get_cached_slots(doctor_id: int) -> Optional[list[dict[str, Any]]]:
    try:
        raw = get_redis().get(_key(doctor_id))
        if raw is None:
            return None
        return json.loads(raw)
    except (redis.RedisError, json.JSONDecodeError):
        return None


def set_cached_slots(doctor_id: int, slots: list[dict[str, Any]]) -> None:
    try:
        get_redis().setex(_key(doctor_id), SLOTS_CACHE_TTL_SECONDS, json.dumps(slots, default=str))
    except redis.RedisError:
        pass  # cache is best-effort


def invalidate_slots_cache(doctor_id: int) -> None:
    try:
        get_redis().delete(_key(doctor_id))
    except redis.RedisError:
        pass
