"""Helpers for generating Zoom-style meeting numbers, passcodes, and links."""
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
    """Return an alphanumeric passcode, like Zoom's join passcode."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def format_meeting_number(number: str) -> str:
    """Format 11 digits as 'XXX XXXX XXXX' for display."""
    if len(number) == 11:
        return f"{number[:3]} {number[3:7]} {number[7:]}"
    return number


def build_invite_link(meeting_number: str, passcode: str | None = None) -> str:
    """Invite link with the passcode embedded (like Zoom's ?pwd=), so link
    recipients don't have to type it while ID-only joiners still must."""
    link = f"{FRONTEND_URL}/j/{meeting_number}"
    if passcode:
        link += f"?pwd={passcode}"
    return link
