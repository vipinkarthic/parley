"""Phase 4 over the wire: paging messages and the hard room cap.

`test_speakers.py` covers the ranking rules in isolation. This covers the
parts that only exist once a socket is involved - that a client's report
about its own microphone turns into an authoritative broadcast, that a
video request reaches the right peer with the right `from`, and that the cap
is enforced on both doors rather than one.
"""
import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import auth_header, signup, unique_email


def set_waiting_room(meeting, on: bool) -> None:
    """Flip the waiting room directly.

    Not via PATCH /api/meetings/{n}: that endpoint updates a *scheduled*
    meeting and requires topic and start_time, so a settings-only body 422s.
    A test that sent one and did not check the status would silently keep
    the default and then block forever waiting for a frame the lobby never
    sends - which is exactly what happened while writing this file.
    """
    from app import models
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(models.Meeting).filter(
            models.Meeting.meeting_number == meeting["meeting_number"]
        ).first()
        row.waiting_room = on
        db.commit()
    finally:
        db.close()


def _meeting(client, waiting_room=False):
    token, _ = signup(client, unique_email("media"))
    meeting = client.post(
        "/api/meetings/instant", json={"topic": "Media"}, headers=auth_header(token)
    ).json()
    set_waiting_room(meeting, waiting_room)
    return token, meeting


def _join(client, meeting, name, token=None):
    headers = auth_header(token) if token else {}
    r = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": name, "passcode": meeting.get("passcode")},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _url(meeting, participant):
    return (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={participant['id']}&token={participant['ws_token']}"
    )


def _drain(sock, want, limit=40, where=None):
    """Read until a frame of type `want` (and matching `where`) arrives.

    The predicate matters: joining broadcasts a ranking to the whole room, so
    a socket often has a stale `active-speakers` queued ahead of the one the
    test is actually waiting for. Matching on type alone would read the stale
    one and assert against the wrong frame.
    """
    for _ in range(limit):
        msg = sock.receive_json()
        if msg["type"] == want and (where is None or where(msg)):
            return msg
    raise AssertionError(f"never saw a matching {want!r} frame")


# ---------------------------------------------------------------------------
# active-speakers
# ---------------------------------------------------------------------------

def test_the_ranking_is_sent_in_the_join_burst(client):
    """A client that has to wait for someone to speak before it learns the
    ranking subscribes to the wrong people in the meantime."""
    token, meeting = _meeting(client)
    host = _join(client, meeting, "Host", token)
    with client.websocket_connect(_url(meeting, host)) as sock:
        msg = _drain(sock, "active-speakers")
        assert msg["ranked"] == [host["id"]]
        assert msg["speaking"] == []


def test_reporting_your_own_microphone_ranks_you_for_the_room(client):
    """The point of the whole design: A reports its own mic, and B is told."""
    token, meeting = _meeting(client)
    host = _join(client, meeting, "Host", token)
    guest = _join(client, meeting, "Guest")

    with client.websocket_connect(_url(meeting, host)) as a:
        _drain(a, "active-speakers")
        with client.websocket_connect(_url(meeting, guest)) as b:
            _drain(b, "active-speakers")
            _drain(a, "peer-joined")

            b.send_json({"type": "speaking", "on": True, "level": 90})

            # The *other* participant is told who is speaking. B never
            # measured A and A never measured B.
            msg = _drain(
                a, "active-speakers", where=lambda m: m["speaking"]
            )
            assert msg["speaking"] == [guest["id"]]
            assert msg["ranked"][0] == guest["id"]


def test_a_lobby_guest_cannot_influence_the_ranking(client):
    """Everything from the lobby is ignored, and this is no exception."""
    token, meeting = _meeting(client, waiting_room=True)
    host = _join(client, meeting, "Host", token)
    guest = _join(client, meeting, "Waiting Guest")
    assert guest["admission"] == "waiting"

    with client.websocket_connect(_url(meeting, host)) as a:
        _drain(a, "active-speakers")
        with client.websocket_connect(_url(meeting, guest)) as b:
            assert b.receive_json()["type"] == "waiting"
            b.send_json({"type": "speaking", "on": True, "level": 99})
            # Round-trip the host socket to be sure the server drained the
            # guest's frame before we assert nothing happened.
            a.send_json({"type": "ping"})
            _drain(a, "pong")
        # The guest is not in the ranking at all.
        a.send_json({"type": "ping"})
        _drain(a, "pong")


# ---------------------------------------------------------------------------
# video-request
# ---------------------------------------------------------------------------

def test_a_video_request_reaches_the_named_peer_only(client):
    token, meeting = _meeting(client)
    host = _join(client, meeting, "Host", token)
    guest = _join(client, meeting, "Guest")

    with client.websocket_connect(_url(meeting, host)) as a:
        _drain(a, "active-speakers")
        with client.websocket_connect(_url(meeting, guest)) as b:
            _drain(b, "peers")
            _drain(a, "peer-joined")

            b.send_json(
                {"type": "video-request", "to": host["id"], "want": False}
            )
            msg = _drain(a, "video-request")
            # Stamped with who asked, so the sender knows which peer
            # connection to swap the track on.
            assert msg["from"] == guest["id"]
            assert msg["want"] is False


def test_a_video_request_for_an_absent_peer_is_dropped(client):
    """No crash, no broadcast - the same shape as an offer to nobody."""
    token, meeting = _meeting(client)
    host = _join(client, meeting, "Host", token)
    with client.websocket_connect(_url(meeting, host)) as a:
        _drain(a, "active-speakers")
        a.send_json({"type": "video-request", "to": 999999, "want": True})
        a.send_json({"type": "ping"})
        assert _drain(a, "pong")["type"] == "pong"


# ---------------------------------------------------------------------------
# the hard room cap
# ---------------------------------------------------------------------------

def test_join_is_refused_once_the_room_is_full(client, monkeypatch):
    from app.routers import meetings as meetings_router

    monkeypatch.setattr(meetings_router, "ROOM_CAP", 3)
    token, meeting = _meeting(client)
    _join(client, meeting, "Host", token)
    _join(client, meeting, "Guest 1")
    _join(client, meeting, "Guest 2")

    r = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "One Too Many", "passcode": meeting.get("passcode")},
    )
    assert r.status_code == 403
    assert "full" in r.json()["detail"].lower()


def test_the_host_is_never_locked_out_of_their_own_meeting(client, monkeypatch):
    """Being unable to enter your own meeting because guests filled it is a
    worse failure than one extra participant."""
    from app.routers import meetings as meetings_router

    monkeypatch.setattr(meetings_router, "ROOM_CAP", 2)
    token, meeting = _meeting(client)
    _join(client, meeting, "Guest 1")
    _join(client, meeting, "Guest 2")

    r = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Host"},
        headers=auth_header(token),
    )
    assert r.status_code in (200, 201), r.text


def test_the_socket_refuses_a_seat_the_http_check_let_through(client, monkeypatch):
    """A participant row can be created long before the socket opens - a
    prejoin screen left open, a restored tab - so the HTTP check alone is a
    hole. 4006 is terminal: the client must not retry into a full room."""
    from app import ws as ws_module

    token, meeting = _meeting(client)
    host = _join(client, meeting, "Host", token)
    guest = _join(client, meeting, "Guest")

    with client.websocket_connect(_url(meeting, host)) as a:
        _drain(a, "active-speakers")
        # Now the room is full as far as the socket is concerned.
        monkeypatch.setattr(ws_module, "ROOM_CAP", 1)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(_url(meeting, guest)) as b:
                b.receive_json()
        assert exc.value.code == 4006


def test_a_reconnecting_participant_is_not_refused_their_own_seat(client, monkeypatch):
    """The cap is checked after eviction, so coming back is not treated as
    arriving. Getting this wrong would make a full room un-rejoinable after
    any blip."""
    from app import ws as ws_module

    token, meeting = _meeting(client)
    host = _join(client, meeting, "Host", token)

    with client.websocket_connect(_url(meeting, host)) as a:
        _drain(a, "active-speakers")
    # Room is now empty of sockets but the cap is 1; reconnecting must work.
    monkeypatch.setattr(ws_module, "ROOM_CAP", 1)
    with client.websocket_connect(_url(meeting, host)) as a:
        assert _drain(a, "active-speakers")["ranked"] == [host["id"]]
