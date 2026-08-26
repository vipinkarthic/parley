"""Meeting lifecycle and join-gate smoke tests.

Scheduled times are always built from the application's own clock helper
(``models.utcnow``) rather than a hardcoded string. That keeps the tests
honest across the timezone change: whatever ``utcnow()`` means, "two hours
after it" is
still in the future and "two hours before it" is still in the past. Hardcoding
a UTC offset here would have made these tests pass for the wrong reason.
"""
from datetime import timedelta

import pytest

from conftest import auth_header, signup, unique_email


def utcnow():
    from app.models import utcnow as app_utcnow

    return app_utcnow()


def _iso(dt):
    return dt.isoformat()


def create_instant(client, token, topic="Smoke Test Meeting"):
    r = client.post(
        "/api/meetings/instant", json={"topic": topic}, headers=auth_header(token)
    )
    assert r.status_code == 201, r.text
    return r.json()


def create_scheduled(client, token, *, start_time, topic="Scheduled Smoke", duration=30):
    r = client.post(
        "/api/meetings/schedule",
        json={"topic": topic, "start_time": _iso(start_time), "duration": duration},
        headers=auth_header(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------
# creation
# --------------------------------------------------------------------------

def test_create_instant_meeting(client, user_token):
    token, user = user_token
    m = create_instant(client, token)

    assert len(m["meeting_number"]) == 11
    assert m["meeting_number"][0] != "0"
    assert m["meeting_type"] == "instant"
    assert m["status"] == "active"
    assert m["host"]["id"] == user["id"]
    # the host, and only the host, is shown the passcode
    assert m["passcode"]
    assert m["passcode"] in m["invite_link"]
    assert m["meeting_number"] in m["invite_link"]


def test_instant_meeting_is_reused_not_duplicated(client, user_token):
    """Clicking New Meeting twice must not strand the first room."""
    token, _ = user_token
    first = create_instant(client, token)
    second = create_instant(client, token)
    assert first["id"] == second["id"]


def test_personal_room_is_stable(client, user_token):
    token, user = user_token
    r = client.post("/api/meetings/personal", headers=auth_header(token))
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["meeting_number"] == user["pmi"]

    r = client.post("/api/meetings/personal", headers=auth_header(token))
    assert r.json()["id"] == first["id"]


def test_create_scheduled_meeting(client, user_token):
    token, _ = user_token
    start = utcnow() + timedelta(hours=3)
    m = create_scheduled(client, token, start_time=start, duration=45)
    assert m["meeting_type"] == "scheduled"
    assert m["status"] == "scheduled"
    assert m["duration"] == 45
    assert m["start_time"] is not None


def test_creating_a_meeting_requires_auth(client):
    assert client.post("/api/meetings/instant", json={"topic": "nope"}).status_code == 401


# --------------------------------------------------------------------------
# listing - these are what the indexes added in this phase exist to serve
# --------------------------------------------------------------------------

def test_upcoming_lists_only_this_hosts_scheduled_meetings_soonest_first(client):
    token_a, _ = signup(client, unique_email("hosta"))
    token_b, _ = signup(client, unique_email("hostb"))

    base = utcnow()
    later = create_scheduled(client, token_a, start_time=base + timedelta(days=2), topic="Later")
    sooner = create_scheduled(client, token_a, start_time=base + timedelta(hours=2), topic="Sooner")
    create_scheduled(client, token_b, start_time=base + timedelta(hours=1), topic="Other host")

    r = client.get("/api/meetings/upcoming", headers=auth_header(token_a))
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()]

    assert sooner["id"] in ids
    assert later["id"] in ids
    assert ids.index(sooner["id"]) < ids.index(later["id"]), "soonest first"
    topics = {m["topic"] for m in r.json()}
    assert "Other host" not in topics, "another host's meetings must not leak"


def test_all_meetings_is_scoped_to_the_host(client):
    token_a, _ = signup(client, unique_email("alla"))
    token_b, user_b = signup(client, unique_email("allb"))
    mine = create_instant(client, token_a, topic="Mine")
    theirs = create_instant(client, token_b, topic="Theirs")

    r = client.get("/api/meetings", headers=auth_header(token_a))
    ids = [m["id"] for m in r.json()]
    assert mine["id"] in ids
    assert theirs["id"] not in ids


def test_ended_meeting_moves_to_recent(client):
    token, _ = signup(client, unique_email("recent"))
    start = utcnow() - timedelta(hours=2)
    m = create_scheduled(client, token, start_time=start, topic="Already Happened")

    r = client.post(
        f"/api/meetings/{m['meeting_number']}/end", headers=auth_header(token)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ended"

    r = client.get("/api/meetings/recent", headers=auth_header(token))
    assert m["id"] in [x["id"] for x in r.json()]


# --------------------------------------------------------------------------
# lookup + passcode disclosure
# --------------------------------------------------------------------------

def test_lookup_by_number_hides_the_passcode_from_non_hosts(client, user_token):
    token, _ = user_token
    m = create_instant(client, token)

    anon = client.get(f"/api/meetings/{m['meeting_number']}")
    assert anon.status_code == 200
    assert anon.json()["passcode"] is None, "passcode must not leak to a stranger"
    assert "pwd=" not in anon.json()["invite_link"]

    as_host = client.get(
        f"/api/meetings/{m['meeting_number']}", headers=auth_header(token)
    )
    assert as_host.json()["passcode"] == m["passcode"]


def test_lookup_accepts_a_spaced_meeting_number(client, user_token):
    token, _ = user_token
    m = create_instant(client, token)
    n = m["meeting_number"]
    spaced = f"{n[:3]} {n[3:7]} {n[7:]}"
    r = client.get(f"/api/meetings/{spaced.replace(' ', '%20')}")
    assert r.status_code == 200
    assert r.json()["id"] == m["id"]


def test_unknown_meeting_is_404(client):
    assert client.get("/api/meetings/12345678901").status_code == 404


# --------------------------------------------------------------------------
# join gates
# --------------------------------------------------------------------------

def test_guest_needs_the_passcode(client, user_token):
    token, _ = user_token
    m = create_instant(client, token)

    denied = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Passerby"},
    )
    assert denied.status_code == 403

    wrong = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Passerby", "passcode": "zzzzzz"},
    )
    assert wrong.status_code == 403


def test_guest_with_the_passcode_lands_in_the_waiting_room(client, user_token):
    token, _ = user_token
    m = create_instant(client, token)

    r = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Passerby", "passcode": m["passcode"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["display_name"] == "Passerby (Guest)"
    assert body["is_meeting_host"] is False
    assert body["admission"] == "waiting"
    assert body["ws_token"]


def test_host_joins_admitted_without_a_passcode(client, user_token):
    token, _ = user_token
    m = create_instant(client, token)

    r = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "The Host"},
        headers=auth_header(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_meeting_host"] is True
    assert body["is_host"] is True
    assert body["admission"] == "admitted"
    assert body["ws_token"]


def test_scheduled_meeting_rejects_an_early_guest(client):
    """The 425 gate compares now() against a stored timestamp - the other
    place a naive/aware mismatch would silently change behaviour."""
    token, _ = signup(client, unique_email("early"))
    start = utcnow() + timedelta(hours=4)
    m = create_scheduled(client, token, start_time=start)

    r = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Eager", "passcode": m["passcode"]},
    )
    assert r.status_code == 425, (
        "a guest joining 4h before the start time must get 425 Too Early; "
        f"got {r.status_code}: {r.text}"
    )


def test_scheduled_meeting_admits_a_guest_once_it_has_started(client):
    """The mirror of the 425 test - proves the gate is not simply always on."""
    token, _ = signup(client, unique_email("ontime"))
    start = utcnow() - timedelta(minutes=30)
    m = create_scheduled(client, token, start_time=start)

    r = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Punctual", "passcode": m["passcode"]},
    )
    assert r.status_code == 201, (
        f"start time is in the past, join should be allowed; got {r.text}"
    )


def test_ended_meeting_cannot_be_joined(client):
    token, _ = signup(client, unique_email("ended"))
    m = create_instant(client, token)
    client.post(f"/api/meetings/{m['meeting_number']}/end", headers=auth_header(token))

    r = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Late", "passcode": m["passcode"]},
    )
    assert r.status_code == 409


def test_locked_meeting_rejects_guests_but_not_the_host(client):
    token, _ = signup(client, unique_email("locked"))
    m = create_instant(client, token)
    r = client.patch(
        f"/api/meetings/{m['meeting_number']}/settings",
        json={"locked": True},
        headers=auth_header(token),
    )
    assert r.status_code == 200
    assert r.json()["settings"]["locked"] is True

    guest = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Nope", "passcode": m["passcode"]},
    )
    assert guest.status_code == 403

    host = client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Host"},
        headers=auth_header(token),
    )
    assert host.status_code == 201


def test_one_active_meeting_per_account(client):
    token, _ = signup(client, unique_email("busy"))
    other_token, _ = signup(client, unique_email("busyother"))

    a = create_instant(client, token, topic="First")
    r = client.post(
        f"/api/meetings/{a['meeting_number']}/join",
        json={"display_name": "Me"},
        headers=auth_header(token),
    )
    assert r.status_code == 201

    b = create_instant(client, other_token, topic="Second")
    r = client.post(
        f"/api/meetings/{b['meeting_number']}/join",
        json={"display_name": "Me", "passcode": b["passcode"]},
        headers=auth_header(token),
    )
    assert r.status_code == 409
    assert "already in another meeting" in r.json()["detail"]


# --------------------------------------------------------------------------
# host-only mutations
# --------------------------------------------------------------------------

def test_only_the_host_can_mutate_a_meeting(client):
    token, _ = signup(client, unique_email("owner"))
    intruder, _ = signup(client, unique_email("intruder"))
    m = create_instant(client, token)
    n = m["meeting_number"]

    assert client.post(f"/api/meetings/{n}/end", headers=auth_header(intruder)).status_code == 403
    assert client.delete(f"/api/meetings/{n}", headers=auth_header(intruder)).status_code == 403
    assert (
        client.patch(
            f"/api/meetings/{n}/settings",
            json={"locked": True},
            headers=auth_header(intruder),
        ).status_code
        == 403
    )


def test_update_and_delete_a_scheduled_meeting(client):
    token, _ = signup(client, unique_email("editor"))
    m = create_scheduled(client, token, start_time=utcnow() + timedelta(days=1))
    n = m["meeting_number"]

    r = client.patch(
        f"/api/meetings/{n}",
        json={
            "topic": "Renamed",
            "description": "New description",
            "start_time": _iso(utcnow() + timedelta(days=2)),
            "duration": 60,
        },
        headers=auth_header(token),
    )
    assert r.status_code == 200
    assert r.json()["topic"] == "Renamed"
    assert r.json()["duration"] == 60

    assert client.delete(f"/api/meetings/{n}", headers=auth_header(token)).status_code == 204
    assert client.get(f"/api/meetings/{n}").status_code == 404


def test_deleting_a_meeting_cascades_to_participants(client, db):
    """participants.meeting_id is ON DELETE CASCADE. SQLite does not enforce
    foreign keys by default and Postgres does, so this is exactly the kind of
    behaviour that changes under the engine swap."""
    from app import models

    token, _ = signup(client, unique_email("cascade"))
    m = create_instant(client, token)
    client.post(
        f"/api/meetings/{m['meeting_number']}/join",
        json={"display_name": "Guest", "passcode": m["passcode"]},
    )
    assert (
        db.query(models.Participant).filter_by(meeting_id=m["id"]).count() >= 1
    )

    r = client.delete(
        f"/api/meetings/{m['meeting_number']}", headers=auth_header(token)
    )
    assert r.status_code == 204

    db.expire_all()
    assert db.query(models.Participant).filter_by(meeting_id=m["id"]).count() == 0
