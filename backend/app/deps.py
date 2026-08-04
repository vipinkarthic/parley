"""Shared FastAPI dependencies for authentication."""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db
from .security import decode_access_token


def _user_from_header(authorization: str | None, db: Session) -> models.User | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return crud.get_user_by_id(db, user_id)


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
