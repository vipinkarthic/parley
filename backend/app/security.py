"""Password hashing, OTP hashing, and JWT helpers."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, JWT_SECRET

# A real bcrypt hash of a value nobody holds, used to spend the same time on a
# login for an address that does not exist as on one that does. Computed once
# at import so the cost is a verify, not a hash-plus-verify.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode("utf-8")


def spend_dummy_verify() -> None:
    """Burn one bcrypt verification, to flatten the unknown-user login path.

    Without this, `user is None` short-circuits before bcrypt ever runs and an
    unknown address answers in ~2ms where a real one takes ~200ms - a 100x
    signal that tells an attacker which addresses are registered, no matter how
    carefully the error message is worded.
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
    """Compare two OTP hashes without leaking where they diverge."""
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
    """Return the full verified claim set, or None if invalid/expired.

    Separate from `decode_access_token` because the caller has to compare
    `iat` against the user's `password_changed_at` to honour a revocation,
    and that needs more than the subject.
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
