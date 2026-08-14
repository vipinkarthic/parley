"""Reconnect, heartbeat and graceful shutdown.

The behaviour under test is what happens when the socket goes away for a
reason that is not the participant's fault: a redeploy, a slept laptop, a
reconnect racing its own predecessor. Before this, all three ended the
meeting.
"""
import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import auth_header, signup, unique_email


def _next(ws, wanted, limit=6):
    """The next frame of a given type.

    A host is greeted with `peers` and then `waiting-list`, so tests cannot
    assume the frame after the first one is their reply. Skipping by type is
    more honest than counting greeting frames that may grow later.
    """
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"no {wanted!r} frame within {limit} messages")


def _close_code(ws, limit=6):
    """The code this socket is closed with, ignoring frames still in flight."""
    for _ in range(limit):
        try:
            ws.receive_json()
        except WebSocketDisconnect as exc:
            return exc.code
    raise AssertionError(f"socket stayed open for {limit} more frames")


def _host_socket(client, topic="Reconnect"):
    token, _ = signup(client, unique_email("recon"))
    meeting = client.post(
        "/api/meetings/instant", json={"topic": topic}, headers=auth_header(token)
    ).json()
    participant = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Host"},
        headers=auth_header(token),
    ).json()
    url = (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={participant['id']}&token={participant['ws_token']}"
    )
    return token, meeting, participant, url


# --- heartbeat ---------------------------------------------------------


def test_ping_is_answered_with_pong(client):
    """The only thing that detects a half-open socket.

    A slept laptop leaves a connection that reports OPEN and never fires a
    close event, so the client's unanswered ping is the sole signal.
    """
    _, _, _, url = _host_socket(client)
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "peers"
        ws.send_json({"type": "ping"})
        assert _next(ws, "pong") == {"type": "pong"}


def test_a_waiting_guest_can_also_heartbeat(client):
    """Answered ahead of the lobby gate, which drops every other message from
    someone who has not been admitted yet - including, before this, their
    heartbeat."""
    _, meeting, _, _ = _host_socket(client)
    guest = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Waiter", "passcode": meeting["passcode"]},
    ).json()
    assert guest["admission"] == "waiting"
    url = (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={guest['id']}&token={guest['ws_token']}"
    )
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "waiting"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


# --- one participant, one socket ---------------------------------------


def test_a_second_socket_evicts_the_first(client):
    """A reconnect regularly arrives before the old socket's close has been
    processed. Both hub dicts are keyed by participant id, so the newcomer
    used to displace the old entry silently - and then the displaced
    handler's teardown announced peer-left and deactivated the row belonging
    to the socket that had just replaced it."""
    from app.ws import hub

    _, meeting, participant, url = _host_socket(client)
    number = meeting["meeting_number"]
    pid = participant["id"]

    with client.websocket_connect(url) as first:
        assert first.receive_json()["type"] == "peers"
        with client.websocket_connect(url) as second:
            assert second.receive_json()["type"] == "peers"
            # the displaced socket is told why, with its own code
            assert _close_code(first) == 4009
            # and the live socket still owns the slot
            assert hub.rooms.get(number, {}).get(pid) is not None
            second.send_json({"type": "ping"})
            assert _next(second, "pong") == {"type": "pong"}


def test_an_ended_meeting_refuses_the_socket(client):
    """Terminal, so the client's reconnect loop stops instead of spinning."""
    token, meeting, _, url = _host_socket(client)
    client.post(
        f"/api/meetings/{meeting['meeting_number']}/end", headers=auth_header(token)
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    assert exc.value.code == 4005


# --- graceful shutdown -------------------------------------------------


def test_a_socket_arriving_mid_drain_is_turned_away_retryably(client):
    """1012 is RFC 6455's "Service Restart" - not an error, and the code the
    client is willing to retry. Admitting them instead would hand out room
    state that is about to vanish with the process."""
    from app.ws import hub

    _, _, _, url = _host_socket(client)
    hub.shutting_down = True
    try:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(url) as ws:
                ws.receive_json()
        assert exc.value.code == 1012
    finally:
        hub.shutting_down = False


def test_drain_closes_every_socket_with_1012():
    """Exercised against a standalone Hub with stub sockets.

    Closing a real socket from the test thread would mean reaching into the
    app's event loop; the logic worth testing is which code goes out, that
    both spaces are covered, and that one socket refusing to close does not
    strand the rest.
    """
    from app.ws import Hub

    class _Stub:
        def __init__(self, explode=False):
            self.closed_with = None
            self.explode = explode

        async def close(self, code=None):
            if self.explode:
                raise RuntimeError("already gone")
            self.closed_with = code

    hub = Hub()
    in_room, exploding, in_lobby = _Stub(), _Stub(explode=True), _Stub()
    hub.add_room("111", 1, in_room, {"id": 1})
    hub.add_room("111", 2, exploding, {"id": 2})
    hub.add_lobby("222", 3, in_lobby, {"id": 3, "displayName": "W"})
    assert hub.socket_count() == 3

    asyncio.run(hub.close_all())

    assert in_room.closed_with == 1012
    assert in_lobby.closed_with == 1012, "a raising close must not strand the rest"
    assert hub.socket_count() == 0


def test_drain_leaves_participants_active(client, db):
    """During a redeploy everyone is about to reconnect, so deactivating them
    would make the API report empty meetings and hostless waiting rooms for
    the length of the deploy - and spend a database write per participant to
    do it."""
    from app import models
    from app.ws import hub

    _, _, participant, url = _host_socket(client)
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "peers"
        hub.shutting_down = True
    try:
        db.expire_all()
        assert db.get(models.Participant, participant["id"]).is_active is True
    finally:
        hub.shutting_down = False
