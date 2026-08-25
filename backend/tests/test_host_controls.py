"""Host controls, on both doors they can be reached through.

There are two: the HTTP settings PATCH the host's security menu writes to,
and the live `settings` / `mute-peer` / `remove-peer` / `end-meeting` frames
the meeting page sends over the socket. Both are privileged, and the thing
worth pinning down is that the privilege is checked server-side rather than
by the frontend hiding a button - so every test here has a non-host trying
the same action and being ignored.
"""
import time
from contextlib import contextmanager

from conftest import auth_header, signup, unique_email
from test_meetings import create_instant
from test_media_plane import _drain, _join, _url, set_waiting_room


def _host_and_meeting(client, topic="Host Controls", waiting_room=False):
    """A host with a fresh instant meeting.

    The waiting room defaults to ON in the model, which matters here: a guest
    who is still in the lobby holds a lobby socket, and lobby sockets are not
    in the room fan-out. Leaving it on made every "the host can mute/remove a
    peer" test block forever on a frame that was never going to be addressed
    to it. Tests that want the lobby ask for it explicitly.
    """
    token, user = signup(client, unique_email("hostctl"))
    meeting = create_instant(client, token, topic=topic)
    set_waiting_room(meeting, waiting_room)
    return token, user, meeting


# ---------------------------------------------------------------------------
# HTTP: PATCH /api/meetings/{n}/settings
# ---------------------------------------------------------------------------

def test_the_host_can_flip_a_setting(client):
    token, _, meeting = _host_and_meeting(client)
    assert meeting["settings"]["locked"] is False

    r = client.patch(
        f"/api/meetings/{meeting['meeting_number']}/settings",
        json={"locked": True},
        headers=auth_header(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["locked"] is True


def test_a_settings_patch_persists(client):
    token, _, meeting = _host_and_meeting(client)
    client.patch(
        f"/api/meetings/{meeting['meeting_number']}/settings",
        json={"allow_chat": False},
        headers=auth_header(token),
    )
    fresh = client.get(
        f"/api/meetings/{meeting['meeting_number']}", headers=auth_header(token)
    ).json()
    assert fresh["settings"]["allow_chat"] is False


def test_a_settings_patch_only_moves_what_it_names(client):
    token, _, meeting = _host_and_meeting(client)
    # Re-read rather than trusting the create response: the helper turns the
    # waiting room off underneath it, so the body from create is already stale.
    before = client.get(
        f"/api/meetings/{meeting['meeting_number']}", headers=auth_header(token)
    ).json()["settings"]

    after = client.patch(
        f"/api/meetings/{meeting['meeting_number']}/settings",
        json={"mute_on_entry": True},
        headers=auth_header(token),
    ).json()["settings"]

    assert after["mute_on_entry"] is True
    for key in set(before) - {"mute_on_entry"}:
        assert after[key] == before[key], key


def test_a_non_host_cannot_change_settings(client):
    _, _, meeting = _host_and_meeting(client)
    other_token, _ = signup(client, unique_email("hostctl-other"))

    r = client.patch(
        f"/api/meetings/{meeting['meeting_number']}/settings",
        json={"locked": True},
        headers=auth_header(other_token),
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Only the host can do that."


def test_changing_settings_requires_a_token(client):
    _, _, meeting = _host_and_meeting(client)
    assert client.patch(
        f"/api/meetings/{meeting['meeting_number']}/settings",
        json={"locked": True},
    ).status_code == 401


def test_settings_on_an_unknown_meeting_is_404(client):
    token, _, _ = _host_and_meeting(client)
    assert client.patch(
        "/api/meetings/00000000000/settings",
        json={"locked": True},
        headers=auth_header(token),
    ).status_code == 404


def test_locking_a_meeting_actually_closes_the_door(client):
    """The setting is only worth anything if the join gate reads it."""
    token, _, meeting = _host_and_meeting(client)
    number, passcode = meeting["meeting_number"], meeting["passcode"]

    before = client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": "Early Guest", "passcode": passcode},
    )
    assert before.status_code in (200, 201), before.text

    client.patch(
        f"/api/meetings/{number}/settings",
        json={"locked": True},
        headers=auth_header(token),
    )

    after = client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": "Late Guest", "passcode": passcode},
    )
    assert after.status_code == 403


def test_unlocking_reopens_it(client):
    token, _, meeting = _host_and_meeting(client)
    number, passcode = meeting["meeting_number"], meeting["passcode"]

    for locked in (True, False):
        client.patch(
            f"/api/meetings/{number}/settings",
            json={"locked": locked},
            headers=auth_header(token),
        )
    r = client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": "Guest", "passcode": passcode},
    )
    assert r.status_code in (200, 201), r.text


# ---------------------------------------------------------------------------
# HTTP: POST /api/meetings/{n}/end
# ---------------------------------------------------------------------------

def test_only_the_host_can_end_a_meeting(client):
    _, _, meeting = _host_and_meeting(client)
    other_token, _ = signup(client, unique_email("hostctl-end"))

    r = client.post(
        f"/api/meetings/{meeting['meeting_number']}/end",
        headers=auth_header(other_token),
    )
    assert r.status_code == 403


def test_ending_a_meeting_closes_it_to_new_joins(client):
    token, _, meeting = _host_and_meeting(client)
    number, passcode = meeting["meeting_number"], meeting["passcode"]

    ended = client.post(f"/api/meetings/{number}/end", headers=auth_header(token))
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "ended"

    r = client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": "Too Late", "passcode": passcode},
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# over the socket
# ---------------------------------------------------------------------------

@contextmanager
def _two_sockets(client, meeting, host, guest):
    """Open a host socket and a guest socket, both past their join burst.

    The ordering is not incidental. The first socket's join burst has to be
    drained before the second one connects: leaving it queued wedges the
    connect handshake and the test blocks forever with no output at all.
    `test_media_plane` establishes the same shape, and this is a helper so
    the host-control tests cannot get it subtly wrong one at a time.
    """
    with client.websocket_connect(_url(meeting, host)) as host_ws:
        _drain(host_ws, "active-speakers")
        with client.websocket_connect(_url(meeting, guest)) as guest_ws:
            _drain(guest_ws, "peers")
            _drain(host_ws, "peer-joined")
            yield host_ws, guest_ws


def _settings_eventually(client, token, meeting, key, want, timeout=5.0):
    """Poll the meeting until `key` reads `want`, or give up.

    The socket handler broadcasts the new settings *before* persisting them,
    and the write goes through `run_in_threadpool`. So a `settings` frame
    arriving proves the room was told, not that the row was updated - reading
    the API the instant the frame lands is a race the test loses on Postgres
    and wins on SQLite, purely because SQLite is quicker. Polling asserts the
    thing that is actually guaranteed: that it lands soon.
    """
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        seen = client.get(
            f"/api/meetings/{meeting['meeting_number']}", headers=auth_header(token)
        ).json()["settings"][key]
        if seen == want:
            return seen
        time.sleep(0.05)
    raise AssertionError(f"{key} was {seen!r}, expected {want!r} within {timeout}s")


def _never_arrives(sock, forbidden):
    """Assert `forbidden` does not turn up before the pong we ask for.

    A bare "read nothing" would pass whether the frame was dropped or merely
    slow, so this posts a ping behind the illegal frame and reads until the
    pong: the server handles messages in order, so a pong with no `forbidden`
    ahead of it means the illegal frame was dropped rather than pending.
    """
    sock.send_json({"type": "ping"})
    for _ in range(40):
        msg = sock.receive_json()
        assert msg["type"] != forbidden, f"a non-host caused a {forbidden!r}"
        if msg["type"] == "pong":
            return
    raise AssertionError("never saw the pong that bounds this assertion")


def test_the_host_can_mute_a_peer(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "mute-peer", "target": guest["id"]})
        assert _drain(guest_ws, "force-mute")["type"] == "force-mute"


def test_a_guest_cannot_mute_a_peer(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        guest_ws.send_json({"type": "mute-peer", "target": host["id"]})
        _never_arrives(host_ws, "force-mute")


def test_the_host_can_mute_everyone(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "mute-all"})
        _drain(guest_ws, "force-mute")


def test_a_guest_cannot_mute_everyone(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        guest_ws.send_json({"type": "mute-all"})
        _never_arrives(host_ws, "force-mute")


def test_the_host_can_remove_a_peer(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "remove-peer", "target": guest["id"]})
        _drain(guest_ws, "removed")
        _drain(host_ws, "peer-left", where=lambda m: m["id"] == guest["id"])


def test_a_guest_cannot_remove_the_host(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        guest_ws.send_json({"type": "remove-peer", "target": host["id"]})
        _never_arrives(host_ws, "removed")


def test_a_host_settings_frame_reaches_the_room(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "settings", "settings": {"allow_chat": False}})
        frame = _drain(
            guest_ws,
            "settings",
            where=lambda m: m["settings"].get("allow_chat") is False,
        )
        assert frame["settings"]["allow_chat"] is False


def test_a_host_settings_frame_is_written_through_to_the_database(client):
    """The security menu is not just a broadcast: a late joiner must see it."""
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "settings", "settings": {"allow_reactions": False}})
        _drain(
            guest_ws,
            "settings",
            where=lambda m: m["settings"].get("allow_reactions") is False,
        )

    _settings_eventually(client, token, meeting, "allow_reactions", False)


def test_a_guest_settings_frame_is_ignored(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        guest_ws.send_json({"type": "settings", "settings": {"allow_chat": False}})
        _never_arrives(host_ws, "settings")

    fresh = client.get(
        f"/api/meetings/{meeting['meeting_number']}", headers=auth_header(token)
    ).json()
    assert fresh["settings"]["allow_chat"] is True


def test_the_host_can_end_the_meeting_over_the_socket(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "end-meeting"})
        _drain(guest_ws, "meeting-ended")

    assert client.get(
        f"/api/meetings/{meeting['meeting_number']}", headers=auth_header(token)
    ).json()["status"] == "ended"


def test_a_guest_cannot_end_the_meeting(client):
    token, _, meeting = _host_and_meeting(client)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _two_sockets(client, meeting, host, guest) as (host_ws, guest_ws):
        guest_ws.send_json({"type": "end-meeting"})
        _never_arrives(host_ws, "meeting-ended")

    assert client.get(
        f"/api/meetings/{meeting['meeting_number']}", headers=auth_header(token)
    ).json()["status"] != "ended"


# ---------------------------------------------------------------------------
# the waiting room, which is the host control with the most moving parts
# ---------------------------------------------------------------------------

@contextmanager
def _host_and_lobby(client, meeting, host, guest):
    """Host in the room, guest held in the lobby.

    A lobby socket gets a `waiting` frame rather than the room's `peers`
    burst, and is deliberately outside the room fan-out - so this cannot
    reuse `_two_sockets`.
    """
    with client.websocket_connect(_url(meeting, host)) as host_ws:
        _drain(host_ws, "active-speakers")
        with client.websocket_connect(_url(meeting, guest)) as guest_ws:
            _drain(guest_ws, "waiting")
            yield host_ws, guest_ws


def test_the_host_admits_a_waiting_guest(client):
    token, _, meeting = _host_and_meeting(client, waiting_room=True)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")
    assert guest["admission"] == "waiting"

    with _host_and_lobby(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "admit", "target": guest["id"]})
        _drain(guest_ws, "admitted")


def test_the_host_denies_a_waiting_guest(client):
    token, _, meeting = _host_and_meeting(client, waiting_room=True)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _host_and_lobby(client, meeting, host, guest) as (host_ws, guest_ws):
        host_ws.send_json({"type": "deny", "target": guest["id"]})
        _drain(guest_ws, "denied")


def test_a_waiting_guest_cannot_admit_themselves(client):
    token, _, meeting = _host_and_meeting(client, waiting_room=True)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _host_and_lobby(client, meeting, host, guest) as (host_ws, guest_ws):
        guest_ws.send_json({"type": "admit", "target": guest["id"]})
        _never_arrives(guest_ws, "admitted")


def test_the_host_is_told_somebody_is_waiting(client):
    token, _, meeting = _host_and_meeting(client, waiting_room=True)
    host = _join(client, meeting, "Host", token=token)
    guest = _join(client, meeting, "Guest")

    with _host_and_lobby(client, meeting, host, guest) as (host_ws, _guest_ws):
        frame = _drain(
            host_ws,
            "waiting-list",
            where=lambda m: any(
                e["id"] == guest["id"] for e in (m.get("waiting") or [])
            ),
        )
        assert any(e["id"] == guest["id"] for e in frame["waiting"])
