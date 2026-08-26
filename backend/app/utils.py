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


def format_meeting_number(number: str) -> str:
    """Format 11 digits as 'XXX XXXX XXXX' for display."""
    if len(number) == 11:
        return f"{number[:3]} {number[3:7]} {number[7:]}"
    return number


def build_invite_link(meeting_number: str, passcode: str | None = None) -> str:
    """Build an invite link, optionally carrying the passcode.

    The passcode rides in the query string so link recipients do not have to
    type it, while someone joining by meeting ID alone still must.
    """
    link = f"{FRONTEND_URL}/j/{meeting_number}"
    if passcode:
        link += f"?pwd={passcode}"
    return link
