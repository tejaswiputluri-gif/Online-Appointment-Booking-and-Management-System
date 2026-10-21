"""
Shared Redis connection.

Interview note:
- One client per process is enough for sync redis-py (connection pool inside).
- On AWS multi-EC2: every app instance points at the same ElastiCache endpoint
  so locks, rate limits, and slot caches are shared cluster-wide.
"""

from functools import lru_cache

import redis

from app.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,  # strings instead of bytes — nicer for JSON cache
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def redis_ping() -> bool:
    try:
        return bool(get_redis().ping())
    except redis.RedisError:
        return False
