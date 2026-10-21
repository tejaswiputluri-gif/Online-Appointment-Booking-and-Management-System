"""
Redis distributed lock using SET NX + EX (SETNX with TTL).

================================================================================
WHY A DISTRIBUTED LOCK INSTEAD OF "JUST A DB UNIQUE CONSTRAINT"?
================================================================================

The booking flow is a classic check-then-act race:

  1. Read slot → is_booked == False
  2. Insert appointment + set is_booked = True
  3. Commit

Two concurrent requests on the SAME slot can both pass step 1 before either
commits step 2/3. Outcomes without coordination:
  - Double booking (if no unique constraint)
  - One IntegrityError / 500 (if unique constraint) — ugly UX, wasted work,
    and under load you get exception storms instead of a clean 409

A UNIQUE constraint is still valuable as *defense in depth*, but it does not:
  - Give the losing request a clear "slot already booked" without parsing DB errors
  - Coordinate work that spans Redis cache invalidation + WebSocket broadcast + DB
  - Protect you if you later add multi-step side effects (payment hold, SMS, etc.)

================================================================================
WHY REDIS SET NX EX (NOT DB ROW LOCKS / SELECT FOR UPDATE ALONE)?
================================================================================

- SELECT FOR UPDATE works *within one database*, but:
  - Holding row locks during external I/O (email, payment) is dangerous
  - If you scale to multiple services / read replicas / eventual consistency
    patterns, the lock must live outside a single Postgres session
- Redis SET key value NX EX ttl is:
  - Atomic (single Redis command)
  - Fast (~sub-ms)
  - Shared across ALL app servers (EC2 ASG behind ALB)
  - Auto-releasing via TTL if a worker crashes mid-flight (no deadlock forever)

DB row locks are still fine as an *additional* guard inside the transaction;
this project emphasizes Redis because interviews often ask about multi-instance
horizontal scaling — the exact AWS EC2 + ElastiCache setup.

================================================================================
MULTI-SERVER EXTENSION
================================================================================

Deploy N FastAPI workers on N EC2 instances (or ECS tasks). They all use the
same Redis URL. The lock key is `lock:slot:{slot_id}` — only one instance
worldwide can hold it. That is the whole point of a *distributed* lock vs an
in-process `threading.Lock` (which only protects one process).

For even stronger guarantees at huge scale, look at Redlock (multi-Redis) or
Redis fencing tokens; for a single Redis primary (typical ElastiCache),
SET NX EX is the industry-standard simple pattern.
================================================================================
"""

from __future__ import annotations

import logging
import uuid
from types import TracebackType
from typing import Optional, Type

import redis

from app.config import get_settings
from app.redis_client.client import get_redis

logger = logging.getLogger(__name__)

# Lua script: release only if we still own the lock (compare token).
# Prevents deleting another request's lock after our TTL expired.
_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LockAcquisitionError(Exception):
    """Raised when another worker already holds the lock for this resource."""

    def __init__(self, resource: str):
        self.resource = resource
        super().__init__(f"Could not acquire lock for '{resource}' — another request holds it.")


class RedisDistributedLock:
    """
    Context-manager lock: SET NX EX on enter, safe Lua release on exit.

    Example:
        with RedisDistributedLock(f"slot:{slot_id}"):
            # critical section — only one holder cluster-wide
            book_in_db(...)
    """

    def __init__(
        self,
        resource: str,
        ttl_seconds: Optional[int] = None,
        client: Optional[redis.Redis] = None,
    ):
        settings = get_settings()
        self.resource = resource
        self.key = f"lock:{resource}"
        self.ttl = ttl_seconds or settings.redis_lock_ttl_seconds
        # Unique token so we only delete *our* lock (avoid releasing someone else's)
        self.token = str(uuid.uuid4())
        self._redis = client or get_redis()
        self._acquired = False

    def acquire(self) -> bool:
        """
        SET key token NX EX ttl

        NX  = Only set if Not eXists  (mutual exclusion)
        EX  = Expire after ttl seconds (crash safety)
        """
        # redis-py: set(..., nx=True, ex=ttl) maps to SET key value NX EX ttl
        ok = self._redis.set(self.key, self.token, nx=True, ex=self.ttl)
        self._acquired = bool(ok)
        if self._acquired:
            logger.debug("Acquired lock %s (ttl=%ss)", self.key, self.ttl)
        else:
            logger.info("Failed to acquire lock %s — contended", self.key)
        return self._acquired

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self._redis.eval(_RELEASE_LUA, 1, self.key, self.token)
            logger.debug("Released lock %s", self.key)
        except redis.RedisError as exc:
            # TTL will still free it; log for ops visibility
            logger.warning("Failed to release lock %s: %s", self.key, exc)
        finally:
            self._acquired = False

    def __enter__(self) -> "RedisDistributedLock":
        if not self.acquire():
            raise LockAcquisitionError(self.resource)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        # Always release — whether DB commit succeeded or raised
        self.release()


def slot_lock(slot_id: int) -> RedisDistributedLock:
    """Convenience factory for booking a specific time slot."""
    return RedisDistributedLock(resource=f"slot:{slot_id}")
