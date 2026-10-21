"""Redis utilities: client, distributed lock, rate limit, slot cache."""

from app.redis_client.cache import get_cached_slots, invalidate_slots_cache, set_cached_slots
from app.redis_client.client import get_redis, redis_ping
from app.redis_client.lock import LockAcquisitionError, RedisDistributedLock, slot_lock
from app.redis_client.rate_limit import check_booking_rate_limit

__all__ = [
    "get_redis",
    "redis_ping",
    "RedisDistributedLock",
    "LockAcquisitionError",
    "slot_lock",
    "check_booking_rate_limit",
    "get_cached_slots",
    "set_cached_slots",
    "invalidate_slots_cache",
]
