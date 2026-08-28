"""Helpers for generating meeting numbers, passcodes, and invite links."""
import secrets
import string

from sqlalchemy.orm import Session

from . import models
from .config import FRONTEND_URL


def generate_meeting_number(db: Session) -> str:
    """Return a unique 11-digit meeting number (first digit non-zero).

    Uses the cryptographically secure `secrets` generator so numbers/passcodes
    aren't predictable from a leaked PRNG state.
    """
    while True:
        number = secrets.choice("123456789") + "".join(
            secrets.choice(string.digits) for _ in range(10)
        )
        exists = (
            db.query(models.Meeting)
            .filter(models.Meeting.meeting_number == number)
            .first()
        )
        if not exists:
            return number


def generate_passcode(length: int = 6) -> str:
    """Return a short alphanumeric passcode for joining a meeting."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_invite_link(meeting_number: str, passcode: str | None = None) -> str:
    """Build an invite link, optionally carrying the passcode.

    The fragment is never sent to a server. The client still reads the old
    query form so existing links keep working.
    """
    link = f"{FRONTEND_URL}/j/{meeting_number}"
    if passcode:
        link += f"#pwd={passcode}"
    return link
