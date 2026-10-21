"""
FastAPI auth dependencies — extract current user and enforce roles.

Usage:
    @router.get("/x")
    def x(user: User = Depends(get_current_user)): ...

    @router.post("/y")
    def y(user: User = Depends(require_roles(UserRole.PATIENT, UserRole.ADMIN))): ...
"""

from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import TokenError, safe_decode
from app.database import get_db
from app.models.user import User, UserRole

# auto_error=False so we can return a consistent 401 body
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = safe_decode(credentials.credentials)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired JWT. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token: missing subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, int(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed: UserRole) -> Callable:
    """
    Factory returning a dependency that enforces RBAC.

    Interview note: role is also in the JWT, but we re-check the DB user.role
    so a role change (e.g. demotion) takes effect without waiting for token expiry.
    """
    allowed_set = set(allowed)

    def _dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{user.role.value}' is not allowed for this action. "
                    f"Required: {[r.value for r in allowed_set]}"
                ),
            )
        return user

    return _dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
PatientUser = Annotated[User, Depends(require_roles(UserRole.PATIENT, UserRole.ADMIN))]
DoctorUser = Annotated[User, Depends(require_roles(UserRole.DOCTOR, UserRole.ADMIN))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
