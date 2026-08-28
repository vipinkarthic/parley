"""Authentication: email/password login + OTP-verified signup."""
import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import config, crud, models, ratelimit, schemas
from ..database import get_db
from ..deps import get_current_user
from ..models import utcnow
from ..emailer import EmailSendError, send_otp_email
from ..security import (
    codes_equal,
    create_access_token,
    hash_code,
    hash_password,
    spend_dummy_verify,
    verify_password,
)

logger = logging.getLogger("parley.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_LIMIT, _LOGIN_WINDOW = 10, 300
_OTP_LIMIT, _OTP_WINDOW = 5, 600
# The verify endpoint used to have no limiter, leaving only the 5-attempt
# counter on the row - which every resend reset back to zero.
_VERIFY_LIMIT, _VERIFY_WINDOW = 10, 600


def _new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# Per-address limits alone let an attacker spray one attempt each across a
# hundred thousand different addresses without tripping anything, and let them
# lock a chosen victim out by burning that victim's budget. The IP window is
# the second axis: wider than the per-address one, because a shared NAT is a
# legitimate source of many logins.
_IP_LOGIN_LIMIT, _IP_LOGIN_WINDOW = 60, 300
_IP_OTP_LIMIT, _IP_OTP_WINDOW = 20, 600


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many attempts. Please wait a bit and try again.",
    )


def _rate_limit(kind: str, email: str, limit: int, window: int) -> None:
    if not ratelimit.allow(f"{kind}:{email.strip().lower()}", limit, window):
        raise _too_many()


def _rate_limit_ip(kind: str, request: Request, limit: int, window: int) -> None:
    if not ratelimit.allow(f"{kind}:ip:{ratelimit.client_ip(request)}", limit, window):
        raise _too_many()


def _send_otp_in_background(email: str, code: str) -> None:
    """Deliver the OTP after the response has already gone out.

    A failure here cannot be reported to the caller, which is the trade being
    made: the pending signup row is already committed, so the user's recourse
    is the resend button rather than a failed signup. Logged loudly, because
    this is now the only place a delivery problem shows up.
    """
    try:
        send_otp_email(email, code)
    except EmailSendError as exc:
        logger.error("background OTP delivery to %s failed: %s", email, exc)


def _dispatch_otp(background: BackgroundTasks, email: str, code: str) -> bool:
    """Queue the OTP and report whether a real email is on its way.

    Signup used to block on Gmail's SMTP round trip, so signup latency *was*
    Gmail's latency - and SMTP being slow or down failed the whole signup with
    a 502, even though the pending row was already written and a resend would
    have worked. Delivery is now a background task and signup no longer
    depends on a third party being up.

    The response contract is unchanged, because EMAIL_ENABLED is known
    synchronously: `email_sent` still says whether to expect an email and
    `dev_code` still carries the code when no mailer is configured. The dev
    path stays inline - it only writes to the log, and deferring it would mean
    the code was not there yet when the developer went looking for it.
    """
    if not config.EMAIL_ENABLED:
        send_otp_email(email, code)
        return False
    background.add_task(_send_otp_in_background, email, code)
    return True


@router.post("/signup/request-otp", response_model=schemas.OtpRequestResponse)
def request_signup_otp(
    data: schemas.SignupRequest,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    _rate_limit_ip("otp", request, _IP_OTP_LIMIT, _IP_OTP_WINDOW)
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
        expires_at=utcnow() + timedelta(minutes=config.OTP_TTL_MINUTES),
    )
    email_sent = _dispatch_otp(background, data.email, code)
    return schemas.OtpRequestResponse(
        email=data.email,
        email_sent=email_sent,
        dev_code=None if email_sent else code,
    )


@router.post("/signup/resend-otp", response_model=schemas.OtpRequestResponse)
def resend_signup_otp(
    data: schemas.ResendOtpRequest,
    background: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    _rate_limit_ip("otp", request, _IP_OTP_LIMIT, _IP_OTP_WINDOW)
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
        expires_at=utcnow() + timedelta(minutes=config.OTP_TTL_MINUTES),
    )
    email_sent = _dispatch_otp(background, data.email, code)
    return schemas.OtpRequestResponse(
        email=data.email,
        email_sent=email_sent,
        dev_code=None if email_sent else code,
    )


@router.post("/signup/verify", response_model=schemas.AuthResponse)
def verify_signup_otp(
    data: schemas.VerifyOtpRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _rate_limit_ip("verify", request, _IP_OTP_LIMIT, _IP_OTP_WINDOW)
    _rate_limit("verify", data.email, _VERIFY_LIMIT, _VERIFY_WINDOW)
    pending = crud.get_pending_signup(db, data.email)
    if pending is None:
        # A successful verify deletes the pending row, so a duplicate
        # submission - a double-tapped button, a retried request whose first
        # response was lost - used to come back as "start again" even though
        # the account had just been created. The code itself cannot be
        # re-checked (its hash went with the row), so this is not a replayed
        # success; it is at least an honest answer about what happened.
        if crud.get_user_by_email(db, data.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already verified. Please log in.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending signup found. Please start again.",
        )
    if utcnow() > pending.expires_at:
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
    if not codes_equal(hash_code(data.code), pending.code_hash):
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
def login(
    data: schemas.LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _rate_limit_ip("login", request, _IP_LOGIN_LIMIT, _IP_LOGIN_WINDOW)
    _rate_limit("login", data.email, _LOGIN_LIMIT, _LOGIN_WINDOW)
    user = crud.get_user_by_email(db, data.email)
    if user is None:
        # Spend the same bcrypt cost the real path would, then fail. Without
        # this the absence of a user short-circuits the verify and answers in
        # ~2ms against ~200ms, which enumerates accounts regardless of how
        # carefully the message below is worded.
        spend_dummy_verify()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    token = create_access_token(user.id)
    return schemas.AuthResponse(token=token, user=schemas.UserOut.model_validate(user))


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


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
