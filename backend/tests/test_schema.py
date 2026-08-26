"""New Phase 1 requirements: UTC timestamps and the indexes.

Unlike the rest of the suite these are expected to FAIL before the Phase 1
changes land and pass after. They are the specification for this phase, kept
separate from the regression tests so the pre-cutover baseline stays readable.
"""
import pytest
from sqlalchemy import inspect

from conftest import ENGINE, IS_POSTGRES


# --------------------------------------------------------------------------
# timezone-aware UTC timestamps
# --------------------------------------------------------------------------

def test_utcnow_helper_returns_timezone_aware_utc():
    """models.utcnow() is the default for every timestamp column in the schema.
    Naive local time in a database that outlives one machine is a bug waiting
    for a deploy in a different timezone."""
    from datetime import timezone

    from app.models import utcnow

    value = utcnow()
    assert value.tzinfo is not None, "utcnow() must be timezone-aware"
    assert value.utcoffset() == timezone.utc.utcoffset(None), "utcnow() must be UTC"


def test_timestamp_columns_declare_timezone():
    """The columns themselves must be timezone-aware, or Postgres stores
    `timestamp` and quietly discards the offset on the way in."""
    from app import models

    expected = [
        (models.User, "created_at"),
        (models.PendingSignup, "created_at"),
        (models.PendingSignup, "expires_at"),
        (models.Meeting, "created_at"),
        (models.Meeting, "start_time"),
        (models.Participant, "joined_at"),
    ]
    missing = []
    for model, column_name in expected:
        column = model.__table__.columns[column_name]
        if not getattr(column.type, "timezone", False):
            missing.append(f"{model.__tablename__}.{column_name}")
    assert not missing, f"columns still storing naive timestamps: {missing}"


@pytest.mark.skipif(not IS_POSTGRES, reason="SQLite has no timestamptz")
def test_stored_timestamps_come_back_aware(client, db):
    from conftest import auth_header, signup, unique_email

    from app import models

    token, _ = signup(client, unique_email("tzcheck"))
    r = client.post(
        "/api/meetings/instant", json={"topic": "TZ"}, headers=auth_header(token)
    )
    db.expire_all()
    row = db.get(models.Meeting, r.json()["id"])
    assert row.created_at.tzinfo is not None, (
        "a timestamp read back from Postgres must carry its timezone"
    )


# --------------------------------------------------------------------------
# indexes on what is actually filtered
# --------------------------------------------------------------------------

def _indexed_columns(table_name: str) -> set[str]:
    """Every column covered by an index or a unique constraint, including
    single-column indexes created implicitly by a unique constraint."""
    inspector = inspect(ENGINE)
    covered: set[str] = set()
    for index in inspector.get_indexes(table_name):
        for column in index["column_names"]:
            if column:
                covered.add(column)
    for constraint in inspector.get_unique_constraints(table_name):
        for column in constraint["column_names"]:
            covered.add(column)
    pk = inspector.get_pk_constraint(table_name)
    for column in pk.get("constrained_columns", []):
        covered.add(column)
    return covered


def test_participants_meeting_id_is_indexed():
    """Every participant lookup filters on meeting_id. Without an index this
    is a sequential scan on the busiest table in the app."""
    assert "meeting_id" in _indexed_columns("participants")


def test_meetings_host_id_is_indexed():
    """Every dashboard list filters meetings by host_id."""
    assert "host_id" in _indexed_columns("meetings")


def test_meetings_start_time_is_indexed():
    """The upcoming-meetings list orders by start_time."""
    assert "start_time" in _indexed_columns("meetings")
