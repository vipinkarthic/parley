"""Data-layer behaviour that must not change across the engine swap.

These are regression tests: green before the cutover, green after. Anything
that is a *new* Phase 1 requirement lives in test_schema.py instead.
"""
from datetime import timedelta

from conftest import auth_header, signup, unique_email


def test_a_created_meeting_is_readable_from_a_separate_session(client, db):
    """Written through the API, read back through a fresh session - proves the
    write actually committed rather than living in an identity map."""
    from app import models

    token, _ = signup(client, unique_email("persist"))
    r = client.post(
        "/api/meetings/instant",
        json={"topic": "Persisted"},
        headers=auth_header(token),
    )
    meeting_id = r.json()["id"]

    db.expire_all()
    row = db.get(models.Meeting, meeting_id)
    assert row is not None
    assert row.topic == "Persisted"
    assert row.created_at is not None


def test_timestamps_are_populated_on_insert(client, db):
    from app import models

    token, user = signup(client, unique_email("stamps"))
    r = client.post(
        "/api/meetings/instant", json={"topic": "Stamped"}, headers=auth_header(token)
    )
    m = r.json()
    client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Someone", "passcode": m["passcode"]},
    )

    db.expire_all()
    user_row = db.get(models.User, user["id"])
    meeting_row = db.get(models.Meeting, m["id"])
    participant = (
        db.query(models.Participant).filter_by(meeting_id=m["id"]).first()
    )

    assert user_row.created_at is not None
    assert meeting_row.created_at is not None
    assert participant.joined_at is not None


def test_created_at_is_close_to_the_app_clock(client, db):
    """The stored timestamp and the application's own clock must agree to
    within a minute. A timezone mismatch shows up here as a multi-hour gap,
    which is the failure mode that broke nothing visibly and everything
    subtly."""
    from app import models
    from app.models import _now

    token, _ = signup(client, unique_email("clock"))
    before = _now()
    r = client.post(
        "/api/meetings/instant", json={"topic": "Clocked"}, headers=auth_header(token)
    )
    after = _now()

    db.expire_all()
    row = db.get(models.Meeting, r.json()["id"])
    stored = row.created_at

    # normalise: compare like with like whatever the awareness regime
    if (stored.tzinfo is None) != (before.tzinfo is None):
        stored = stored.replace(tzinfo=before.tzinfo)

    assert before - timedelta(minutes=1) <= stored <= after + timedelta(minutes=1), (
        f"stored created_at {stored} is not near the app clock "
        f"({before} .. {after}) - timezone mismatch"
    )


def test_ordering_by_start_time_is_correct(client):
    """list_upcoming orders by start_time ascending; if timestamps are stored
    inconsistently the order silently scrambles."""
    from app.models import _now

    token, _ = signup(client, unique_email("ordering"))
    base = _now()
    offsets = [timedelta(hours=5), timedelta(hours=1), timedelta(days=3), timedelta(hours=9)]
    created = []
    for i, off in enumerate(offsets):
        r = client.post(
            "/api/meetings/schedule",
            json={
                "topic": f"Meeting {i}",
                "start_time": (base + off).isoformat(),
                "duration": 30,
            },
            headers=auth_header(token),
        )
        assert r.status_code == 201, r.text
        created.append((base + off, r.json()["id"]))

    r = client.get("/api/meetings/upcoming", headers=auth_header(token))
    got = [m["id"] for m in r.json()]
    expected = [mid for _, mid in sorted(created, key=lambda x: x[0])]
    assert got == expected, "upcoming meetings must come back soonest-first"


def test_unique_constraints_hold(client, db):
    """Duplicate emails and meeting numbers must be impossible. SQLite and
    Postgres both enforce these, but the error type differs, so the app must
    not be relying on catching one specific exception."""
    from sqlalchemy.exc import IntegrityError

    from app import models

    email = unique_email("unique")
    signup(client, email)

    session = db
    session.add(
        models.User(
            name="Impostor",
            email=email,
            password_hash="x",
            is_verified=True,
            avatar_color="#000000",
            pmi="12345678901",
        )
    )
    try:
        session.commit()
        raised = False
    except IntegrityError:
        raised = True
        session.rollback()
    assert raised, "users.email must be unique"


def test_participant_count_reflects_active_joins(client):
    token, _ = signup(client, unique_email("counting"))
    r = client.post(
        "/api/meetings/instant", json={"topic": "Counted"}, headers=auth_header(token)
    )
    m = r.json()
    assert m["participant_count"] == 0

    for name in ("One", "Two", "Three"):
        rr = client.post(
            f"/api/meetings/{m['meeting_number']}/join",
            json={"display_name": name, "passcode": m["passcode"]},
        )
        assert rr.status_code == 201

    r = client.get(
        f"/api/meetings/{m['meeting_number']}", headers=auth_header(token)
    )
    assert r.json()["participant_count"] == 3
