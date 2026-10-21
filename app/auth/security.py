"""
Password hashing and JWT create/decode helpers.

Interview note:
- passlib + bcrypt for passwords (never store plaintext).
- JWT (HS256) for stateless auth — scales across multiple EC2 instances
  without sticky sessions. Trade-off: revocation requires a denylist (Redis)
  or short TTLs; we use short-ish access tokens for this project.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()

# bcrypt via passlib — truncate is handled by bcrypt's 72-byte limit
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str | int,
    role: str,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    """
    Build a signed JWT.

    Claims:
      - sub: user id (stringified per JWT convention)
      - role: patient | doctor | admin  (used for RBAC without a DB hit)
      - exp: expiry
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode + verify signature/expiry.

    Raises JWTError (caught by auth dependencies → 401).
    """
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


class TokenError(Exception):
    """Raised when a token is missing, expired, or malformed."""

    pass


def safe_decode(token: str) -> dict[str, Any]:
    try:
        return decode_access_token(token)
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc
