"""Password hashing, OTP hashing, and JWT helpers."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET

# Computed once so the equaliser below costs one verify, not a hash too.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode("utf-8")


def spend_dummy_verify() -> None:
    """Flatten the unknown user login path.

    Skipping bcrypt answers 100x faster, which enumerates accounts.
    """
    bcrypt.checkpw(b"parley-timing-equaliser", _DUMMY_HASH.encode("utf-8"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except ValueError:
        return False


def hash_code(code: str) -> str:
    """OTPs are short-lived; a fast SHA-256 hash is sufficient here."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def codes_equal(a: str, b: str) -> bool:
    """Compare OTP hashes without leaking where they diverge."""
    return hmac.compare_digest(a, b)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id encoded in the token, or None if invalid/expired."""
    claims = decode_access_token_claims(token)
    if claims is None:
        return None
    try:
        return int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        return None


def decode_access_token_claims(token: str) -> dict | None:
    """Return the verified claims, or None if invalid or expired.

    Revocation needs iat, so the subject alone is not enough.
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
