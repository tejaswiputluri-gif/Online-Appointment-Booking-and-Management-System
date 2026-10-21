"""
SQLAlchemy engine / session factory.

Interview note:
- We use a sync SQLAlchemy session for clarity in interviews (easier to reason
  about transaction boundaries with Redis locks). Async SQLAlchemy is fine in
  production FastAPI apps; the locking pattern is identical.
- pool_pre_ping=True detects stale RDS connections after idle timeouts.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Small pools for free-tier hosts (Render Free = 512MB RAM)
    pool_size=2,
    max_overflow=3,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(retries: int = 10, delay_seconds: float = 3.0) -> None:
    """Create tables if they do not exist (dev convenience). Prefer Alembic in prod.

    Retries help on Render/AWS when the web service boots before Postgres is ready.
    """
    import logging
    import time

    from sqlalchemy.exc import OperationalError

    # Import models so they register with Base.metadata
    from app.models import appointment, doctor, time_slot, user  # noqa: F401

    logger = logging.getLogger(__name__)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database schema ready (attempt %s)", attempt)
            return
        except OperationalError as exc:
            last_error = exc
            logger.warning(
                "DB not ready (attempt %s/%s): %s", attempt, retries, exc.orig if hasattr(exc, "orig") else exc
            )
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to database after {retries} attempts") from last_error
