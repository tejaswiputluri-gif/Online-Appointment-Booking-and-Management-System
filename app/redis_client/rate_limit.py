"""
Redis-backed fixed-window rate limiter for the booking endpoint.

Interview note:
- Key: ratelimit:book:{user_id}:{YYYYMMDDHHMM}  (per-user per calendar minute)
- INCR + EXPIRE is atomic enough for this portfolio; for stricter limits use
  a Lua sliding window or Redis Cell / token bucket.
- Shared Redis ⇒ limit is global across all EC2 instances (not per-process).
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis
from fastapi import HTTPException, status

from app.config import get_settings
from app.redis_client.client import get_redis


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Rate limit exceeded")


def check_booking_rate_limit(user_id: int) -> None:
    """
    Allow at most N booking attempts per minute per user.

    Raises HTTPException 429 if exceeded.
    """
    settings = get_settings()
    limit = settings.booking_rate_limit_per_minute
    now = datetime.now(timezone.utc)
    window = now.strftime("%Y%m%d%H%M")  # 1-minute fixed window
    key = f"ratelimit:book:{user_id}:{window}"

    r = get_redis()
    try:
        # Pipeline: INCR then ensure TTL (first hit sets expiry)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        count, _ = pipe.execute()
    except redis.RedisError:
        # Fail-open on Redis outage for rate limit (availability over strict limit).
        # Locks should still fail-closed — see booking service.
        return

    if int(count) > limit:
        retry_after = 60 - now.second
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Booking rate limit exceeded: max {limit} attempts per minute. "
                f"Retry in ~{retry_after}s."
            ),
            headers={"Retry-After": str(retry_after)},
        )
