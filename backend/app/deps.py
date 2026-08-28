"""Shared FastAPI dependencies for authentication."""
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db
from .security import decode_access_token_claims


def _user_from_header(authorization: str | None, db: Session) -> models.User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    claims = decode_access_token_claims(token)
    if claims is None:
        return None
    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    user = crud.get_user_by_id(db, user_id)
    if user is None:
        return None
    if _issued_before_password_change(claims, user):
        return None
    return user


def _issued_before_password_change(claims: dict, user: models.User) -> bool:
    """Whether this token predates the last password change.

    A token with no iat cannot be placed in time, so it is refused.
    """
    changed_at = getattr(user, "password_changed_at", None)
    if changed_at is None:
        return False
    issued_at = claims.get("iat")
    if issued_at is None:
        return True
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    # Whole seconds, because iat carries nothing finer and a fresh token
    # would otherwise read as older than its own stamp.
    return int(issued_at) < int(changed_at.timestamp())


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    """Require a valid Bearer token; raise 401 otherwise."""
    user = _user_from_header(authorization, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User | None:
    """Return the user if a valid token is present, else None (guests allowed)."""
    return _user_from_header(authorization, db)
