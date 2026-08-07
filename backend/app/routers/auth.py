"""Authentication: email/password login + OTP-verified signup."""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import config, crud, models, ratelimit, schemas
from ..database import get_db
from ..deps import get_current_user
from ..emailer import EmailSendError, send_otp_email
from ..security import (
    create_access_token,
    hash_code,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_LIMIT, _LOGIN_WINDOW = 10, 300
_OTP_LIMIT, _OTP_WINDOW = 5, 600


def _new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _rate_limit(kind: str, email: str, limit: int, window: int) -> None:
    if not ratelimit.allow(f"{kind}:{email.strip().lower()}", limit, window):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a bit and try again.",
        )


def _dispatch_otp(email: str, code: str) -> bool:
    """Send the OTP, converting a delivery failure into a clean 502."""
    try:
        return send_otp_email(email, code)
    except EmailSendError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


@router.post("/signup/request-otp", response_model=schemas.OtpRequestResponse)
def request_signup_otp(data: schemas.SignupRequest, db: Session = Depends(get_db)):
    _rate_limit("otp", data.email, _OTP_LIMIT, _OTP_WINDOW)
    if crud.get_user_by_email(db, data.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Please log in.",
        )

    code = _new_otp()
    crud.upsert_pending_signup(
        db,
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password),
        code_hash=hash_code(code),
        expires_at=datetime.now() + timedelta(minutes=config.OTP_TTL_MINUTES),
    )
    email_sent = _dispatch_otp(data.email, code)
    return schemas.OtpRequestResponse(
        email=data.email,
        email_sent=email_sent,
        dev_code=None if email_sent else code,
    )


@router.post("/signup/resend-otp", response_model=schemas.OtpRequestResponse)
def resend_signup_otp(data: schemas.ResendOtpRequest, db: Session = Depends(get_db)):
    _rate_limit("otp", data.email, _OTP_LIMIT, _OTP_WINDOW)
    pending = crud.get_pending_signup(db, data.email)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending signup for this email. Start again.",
        )
    code = _new_otp()
    crud.upsert_pending_signup(
        db,
        email=pending.email,
        name=pending.name,
        password_hash=pending.password_hash,
        code_hash=hash_code(code),
        expires_at=datetime.now() + timedelta(minutes=config.OTP_TTL_MINUTES),
    )
    email_sent = _dispatch_otp(data.email, code)
    return schemas.OtpRequestResponse(
        email=data.email,
        email_sent=email_sent,
        dev_code=None if email_sent else code,
    )


@router.post("/signup/verify", response_model=schemas.AuthResponse)
def verify_signup_otp(data: schemas.VerifyOtpRequest, db: Session = Depends(get_db)):
    pending = crud.get_pending_signup(db, data.email)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending signup found. Please start again.",
        )
    if datetime.now() > pending.expires_at:
        crud.delete_pending_signup(db, pending)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Your code has expired. Please request a new one.",
        )
    if pending.attempts >= config.OTP_MAX_ATTEMPTS:
        crud.delete_pending_signup(db, pending)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many incorrect attempts. Please start again.",
        )
    if hash_code(data.code) != pending.code_hash:
        pending.attempts += 1
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect code. Please check and try again.",
        )

    if crud.get_user_by_email(db, pending.email):
        crud.delete_pending_signup(db, pending)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already registered. Please log in.",
        )

    user = crud.create_user(
        db,
        name=pending.name,
        email=pending.email,
        password_hash=pending.password_hash,
    )
    crud.delete_pending_signup(db, pending)
    token = create_access_token(user.id)
    return schemas.AuthResponse(token=token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.AuthResponse)
def login(data: schemas.LoginRequest, db: Session = Depends(get_db)):
    _rate_limit("login", data.email, _LOGIN_LIMIT, _LOGIN_WINDOW)
    user = crud.get_user_by_email(db, data.email)
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = create_access_token(user.id)
    return schemas.AuthResponse(token=token, user=schemas.UserOut.model_validate(user))


@router.get("/me", response_model=schemas.UserOut)
def me(current=Depends(get_current_user)):
    return current


@router.post("/change-password")
def change_password(
    data: schemas.ChangePassword,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your current password is incorrect.",
        )
    crud.change_password(db, user, hash_password(data.new_password))
    return {"ok": True}
