"""User-scoped routes: contacts directory and preferences."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/contacts", response_model=list[schemas.ContactOut])
def contacts(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return crud.list_contacts(db, exclude_user_id=user.id)


@router.get("/preferences", response_model=schemas.PreferencesOut)
def get_preferences(user: models.User = Depends(get_current_user)):
    return user


@router.patch("/preferences", response_model=schemas.PreferencesOut)
def update_preferences(
    data: schemas.PreferencesUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return crud.update_preferences(db, user, data)
