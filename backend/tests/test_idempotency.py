"""Joins and OTP verifications that get submitted twice.

Every case here is a lost-response retry, not a hypothetical: a join that
committed a row the browser never learned about used to leave a tile nobody
was behind, and a re-submitted OTP reported "start again" for an account it
had just created.
"""
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import auth_header, signup, unique_email


def _eventually(predicate, timeout=2.0):
    """Wait for a server-side effect of closing a socket.

    TestClient's websocket context manager returns as soon as the close frame
    is sent; the handler's teardown runs a beat later on the app's own task.
    Polling is the honest way to assert on it - a bare sleep either flakes or
    wastes the same time on every run.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _meeting(client):
    token, _ = signup(client, unique_email("idem"))
    r = client.post(
        "/api/meetings/instant", json={"topic": "Idempotency"}, headers=auth_header(token)
    )
    return token, r.json()


def _join(client, number, name, key=None, passcode=None, token=None):
    headers = auth_header(token) if token else {}
    if key:
        headers["Idempotency-Key"] = key
    return client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": name, "passcode": passcode},
        headers=headers,
    )


def test_replayed_join_returns_the_same_participant(client):
    token, meeting = _meeting(client)
    first = _join(client, meeting["meeting_number"], "Host", key="k-host-1", token=token)
    second = _join(client, meeting["meeting_number"], "Host", key="k-host-1", token=token)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    # The socket authenticates with this, so a replay handing back a different
    # token would leave the first browser unable to connect.
    assert first.json()["ws_token"] == second.json()["ws_token"]


def test_replayed_guest_join_does_not_duplicate_the_row(client, db):
    """The case the key exists for.

    A guest has no user_id, so `deactivate_user_in_meeting` - which is what
    keeps a logged-in user from stacking up rows - does nothing for them. Two
    joins without a key are two active participants and two ghost tiles.
    """
    from app import models

    _, meeting = _meeting(client)
    number, passcode = meeting["meeting_number"], meeting["passcode"]

    _join(client, number, "Guest A", key="k-guest-1", passcode=passcode)
    _join(client, number, "Guest A", key="k-guest-1", passcode=passcode)

    rows = (
        db.query(models.Participant)
        .filter(
            models.Participant.meeting_id == meeting["id"],
            models.Participant.join_key == "k-guest-1",
        )
        .all()
    )
    assert len(rows) == 1


def test_distinct_keys_are_distinct_participants(client):
    """Two real people joining must not be collapsed into one."""
    _, meeting = _meeting(client)
    number, passcode = meeting["meeting_number"], meeting["passcode"]
    a = _join(client, number, "Guest A", key="k-a", passcode=passcode).json()
    b = _join(client, number, "Guest B", key="k-b", passcode=passcode).json()
    assert a["id"] != b["id"]


def test_join_without_a_key_still_works(client):
    """The header is optional - an older frontend must keep joining."""
    token, meeting = _meeting(client)
    r = _join(client, meeting["meeting_number"], "No Key", token=token)
    assert r.status_code == 201
    assert r.json()["ws_token"]


def test_two_keyless_joins_coexist(client):
    """The unique constraint must not turn "no key" into a collision.

    `UNIQUE (meeting_id, join_key)` with a NULL key relies on NULLs not being
    equal to each other, which is standard and true on both SQLite and
    Postgres - but it is the kind of assumption that only fails in production,
    on the engine the tests were not run against.
    """
    _, meeting = _meeting(client)
    number, passcode = meeting["meeting_number"], meeting["passcode"]
    a = _join(client, number, "Keyless A", passcode=passcode)
    b = _join(client, number, "Keyless B", passcode=passcode)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


def test_replay_is_refused_once_the_meeting_has_ended(client):
    token, meeting = _meeting(client)
    number = meeting["meeting_number"]
    _join(client, number, "Host", key="k-ended", token=token)
    client.post(f"/api/meetings/{number}/end", headers=auth_header(token))
    again = _join(client, number, "Host", key="k-ended", token=token)
    assert again.status_code == 409


def test_second_otp_verify_says_already_verified(client):
    """Not 404 "start again" - the account exists, so say so."""
    email = unique_email("twice")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "Twice", "email": email, "password": "password123"},
    )
    code = r.json()["dev_code"]
    first = client.post("/auth/signup/verify", json={"email": email, "code": code})
    assert first.status_code == 200
    second = client.post("/auth/signup/verify", json={"email": email, "code": code})
    assert second.status_code == 409
    assert "log in" in second.json()["detail"].lower()


def test_unknown_email_verify_still_says_start_again(client):
    r = client.post(
        "/auth/signup/verify",
        json={"email": unique_email("nobody"), "code": "000000"},
    )
    assert r.status_code == 404


def test_a_reconnecting_socket_reactivates_the_participant(client, db):
    """A dropped socket deactivates the row; presence is read off that flag."""
    from app import models

    token, meeting = _meeting(client)
    number = meeting["meeting_number"]
    p = _join(client, number, "Reconnector", key="k-recon", token=token).json()
    url = f"/ws/meetings/{number}?pid={p['id']}&token={p['ws_token']}"

    def active():
        db.expire_all()
        return db.get(models.Participant, p["id"]).is_active

    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "peers"
    assert _eventually(lambda: active() is False), "drop did not deactivate"

    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "peers"
        assert active() is True, "reconnect did not reactivate"


def test_a_denied_guest_cannot_reconnect_into_the_room(client):
    """Denial has to be terminal.

    A denied guest keeps a valid ws_token, and "denied" is not "waiting", so
    before this the reconnect path walked them straight into the room the host
    had just refused them.
    """
    from app import crud, models
    from app.database import SessionLocal

    token, meeting = _meeting(client)
    number = meeting["meeting_number"]
    guest = _join(
        client, number, "Denied", key="k-denied", passcode=meeting["passcode"]
    ).json()

    session = SessionLocal()
    try:
        row = session.get(models.Participant, guest["id"])
        crud.set_admission(session, row, "denied")
    finally:
        session.close()

    url = f"/ws/meetings/{number}?pid={guest['id']}&token={guest['ws_token']}"
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    assert exc.value.code == 4004
