"""Custom SQLAlchemy column types."""
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC on the Python side.

    Postgres stores these as ``timestamptz`` and hands back aware datetimes on
    its own. SQLite has no timezone-aware type: it stores whatever string it is
    given and returns a *naive* datetime, which would then raise TypeError the
    moment it met an aware ``datetime.now(timezone.utc)`` - and the OTP expiry
    check is exactly that comparison.

    Normalising in both directions means application code never has to know
    which engine it is talking to, and a naive datetime can never reach the
    database.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # The API accepts a naive timestamp rather than rejecting it, so an
            # older frontend build that has not yet been redeployed keeps
            # working. Interpreting it as UTC is the only defensible reading:
            # the server's local timezone is an accident of where it is hosted.
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # SQLite. The stored value is UTC because bind put it there.
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
