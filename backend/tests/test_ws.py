"""WebSocket signalling smoke tests.

The socket authenticates by looking the participant's ``ws_token`` up in the
database on every connect, so this exercises the data layer from the async
side of the app - the one place sync DB calls sit inside an ``async def``.
"""
import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import auth_header, signup, unique_email


def _host_meeting_and_participant(client):
    token, _ = signup(client, unique_email("wshost"))
    r = client.post(
        "/api/meetings/instant", json={"topic": "WS Test"}, headers=auth_header(token)
    )
    meeting = r.json()
    r = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "WS Host"},
        headers=auth_header(token),
    )
    return meeting, r.json()


def test_socket_accepts_a_valid_token(client):
    meeting, participant = _host_meeting_and_participant(client)
    url = (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={participant['id']}&token={participant['ws_token']}"
    )
    with client.websocket_connect(url) as ws:
        msg = ws.receive_json()
        # the host is admitted, so the first frame is the peer list
        assert msg["type"] == "peers"
        assert msg["peers"] == []


def test_socket_rejects_a_forged_token(client):
    meeting, participant = _host_meeting_and_participant(client)
    url = (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={participant['id']}&token=forged-token"
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    assert exc.value.code == 4003


def test_socket_rejects_an_unknown_participant_id(client):
    meeting, participant = _host_meeting_and_participant(client)
    url = (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid=99999999&token={participant['ws_token']}"
    )
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    assert exc.value.code == 4003


def test_socket_rejects_a_non_numeric_pid(client):
    meeting, _ = _host_meeting_and_participant(client)
    url = f"/ws/meetings/{meeting['meeting_number']}?pid=abc&token=x"
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_json()
    assert exc.value.code == 4001


def test_waiting_guest_is_told_it_is_waiting(client):
    """A guest held in the lobby gets 'waiting', not the peer list - the
    admission value is read from the database at connect time."""
    meeting, _ = _host_meeting_and_participant(client)
    r = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Waiter", "passcode": meeting["passcode"]},
    )
    guest = r.json()
    assert guest["admission"] == "waiting"

    url = (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={guest['id']}&token={guest['ws_token']}"
    )
    with client.websocket_connect(url) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "waiting"
