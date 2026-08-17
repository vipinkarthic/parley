"""Phase 3: the signalling hub must not block, and must not hit the database
on the hot path.

Two claims, and both are the sort that quietly regress the moment someone adds
an `await` in the wrong place, so they are asserted rather than remembered:

1. ``Hub.broadcast`` fans out concurrently. A receiver whose send is slow must
   not delay the receivers behind it.
2. Relaying signalling opens **no** database session at all. Everything the
   connection needs is loaded once, in one session, at connect.

The second is the one that matters in production. Render runs in Oregon and
Neon in Singapore, so a synchronous session opened inside the ``async def``
handler blocks the event loop - and therefore every meeting on the instance -
for a cross-Pacific round trip.
"""
import asyncio
import time

import pytest

from app import ws as ws_module
from app.ws import Hub

from conftest import auth_header, signup, unique_email


# ---------------------------------------------------------------------------
# 1. Fan-out is concurrent
# ---------------------------------------------------------------------------

class _StubSocket:
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.delivered_at = None

    async def send_text(self, _text):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.delivered_at = time.perf_counter()


@pytest.mark.parametrize("slow_count", [1, 3])
def test_a_slow_receiver_does_not_delay_the_others(slow_count):
    """The head-of-line property, stated as a bound rather than a ratio.

    With `slow_count` receivers each taking 100ms, a sequential loop delivers
    to the healthy peers only after all of them have finished - so the fast
    peers would see slow_count * 100ms. Concurrently they see ~0. The
    assertion allows a very generous 50ms so it cannot flake on a loaded CI
    box, while still failing outright if the awaits go back to being serial.
    """
    delay = 0.1
    hub = Hub()
    number = "00000000000"
    slow, fast = [], []
    for pid in range(1, 9):
        sock = _StubSocket(delay if pid <= slow_count else 0.0)
        (slow if pid <= slow_count else fast).append(sock)
        hub.add_room(number, pid, sock, {"id": pid})

    async def run():
        started = time.perf_counter()
        await hub.broadcast(number, {"type": "chat", "text": "hi"})
        return started

    started = asyncio.run(run())

    assert all(s.delivered_at is not None for s in slow + fast)
    worst_fast = max((s.delivered_at - started) for s in fast)
    assert worst_fast < 0.05, (
        f"a healthy receiver waited {worst_fast * 1000:.0f}ms behind "
        f"{slow_count} slow one(s); the fan-out is running sequentially"
    )
    # And the whole broadcast still costs about one slow send, not N of them.
    whole = max((s.delivered_at - started) for s in slow + fast)
    assert whole < delay * 2


def test_broadcast_survives_a_socket_that_raises():
    """One dead socket must not abort delivery to everyone else."""
    class _Broken:
        async def send_text(self, _text):
            raise RuntimeError("socket is gone")

    hub = Hub()
    number = "00000000000"
    good_a, good_b = _StubSocket(), _StubSocket()
    hub.add_room(number, 1, good_a, {"id": 1})
    hub.add_room(number, 2, _Broken(), {"id": 2})
    hub.add_room(number, 3, good_b, {"id": 3})

    asyncio.run(hub.broadcast(number, {"type": "chat", "text": "hi"}))
    assert good_a.delivered_at is not None
    assert good_b.delivered_at is not None


def test_broadcast_honours_exclude():
    hub = Hub()
    number = "00000000000"
    a, b = _StubSocket(), _StubSocket()
    hub.add_room(number, 1, a, {"id": 1})
    hub.add_room(number, 2, b, {"id": 2})
    asyncio.run(hub.broadcast(number, {"type": "chat"}, exclude=1))
    assert a.delivered_at is None
    assert b.delivered_at is not None


# ---------------------------------------------------------------------------
# 2. Session accounting
# ---------------------------------------------------------------------------

@pytest.fixture
def count_sessions(monkeypatch):
    """Count every SessionLocal() the signalling module opens.

    Patched on `app.ws` rather than on `app.database`, so this measures the
    signalling handler specifically and is not confused by the HTTP requests
    the test uses to set the meeting up.
    """
    real = ws_module.SessionLocal
    calls = []

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(ws_module, "SessionLocal", counting)
    return calls


def _meeting_with_host(client):
    token, _ = signup(client, unique_email("perf"))
    meeting = client.post(
        "/api/meetings/instant", json={"topic": "Perf"}, headers=auth_header(token)
    ).json()
    participant = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Perf Host"},
        headers=auth_header(token),
    ).json()
    return token, meeting, participant


def _ws_url(meeting, participant):
    return (
        f"/ws/meetings/{meeting['meeting_number']}"
        f"?pid={participant['id']}&token={participant['ws_token']}"
    )


def test_connect_opens_exactly_one_session(client, count_sessions):
    """Authentication, the terminal-state checks, the settings snapshot and
    the reconnect reactivation are one transaction, not two."""
    _, meeting, participant = _meeting_with_host(client)
    with client.websocket_connect(_ws_url(meeting, participant)) as sock:
        assert sock.receive_json()["type"] == "peers"
        opened_at_connect = len(count_sessions)
    assert opened_at_connect == 1, (
        f"connect opened {opened_at_connect} sessions; it should load "
        "everything it needs in one"
    )


def test_relaying_signalling_opens_no_session(client, count_sessions):
    """The hot path - offers, answers, ICE, mute state, chat, reactions,
    raised hands, screen share, heartbeats - must never touch the database."""
    _, meeting, participant = _meeting_with_host(client)
    with client.websocket_connect(_ws_url(meeting, participant)) as sock:
        sock.receive_json()
        count_sessions.clear()

        hot_path = [
            {"type": "ping"},
            {"type": "offer", "to": 999999, "sdp": "v=0"},
            {"type": "answer", "to": 999999, "sdp": "v=0"},
            {"type": "ice", "to": 999999, "candidate": "candidate:0"},
            {"type": "state", "muted": True, "videoOn": False},
            {"type": "state", "muted": False, "videoOn": True},
            {"type": "chat", "text": "hello"},
            {"type": "reaction", "emoji": "*"},
            {"type": "hand", "raised": True},
            {"type": "share", "on": True, "streamId": "s1"},
            {"type": "share", "on": False},
            {"type": "spotlight", "target": 1},
        ]
        for message in hot_path:
            sock.send_json(message)
        # A round trip that is answered proves the server drained the queue
        # above before replying, so the count below is not read too early.
        sock.send_json({"type": "ping"})
        while sock.receive_json()["type"] != "pong":
            pass

        assert count_sessions == [], (
            f"{len(count_sessions)} database session(s) opened while relaying "
            "signalling; the hot path must not hit the database"
        )


def test_a_rename_persists_and_costs_one_session(client, count_sessions):
    """Renames do have to be written down - but exactly once, and the room is
    told before the write rather than after it."""
    _, meeting, participant = _meeting_with_host(client)
    with client.websocket_connect(_ws_url(meeting, participant)) as sock:
        sock.receive_json()
        count_sessions.clear()
        sock.send_json({"type": "rename", "name": "Renamed Host"})
        sock.send_json({"type": "ping"})
        while sock.receive_json()["type"] != "pong":
            pass
        # Read before the socket closes: teardown deactivates the participant,
        # which is a legitimate write and would otherwise be counted here.
        during_rename = len(count_sessions)
    assert during_rename == 1

    from app import models
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        assert db.get(models.Participant, participant["id"]).display_name == (
            "Renamed Host"
        )
    finally:
        db.close()


def test_admitting_a_lobby_full_of_guests_is_one_transaction(client, count_sessions):
    """`admit-all` used to open one session per guest, serially. The write is
    now batched, so the count does not grow with the size of the lobby."""
    token, meeting, host = _meeting_with_host(client)
    number = meeting["meeting_number"]
    # Waiting room on, so guests queue rather than walk straight in.
    client.patch(
        f"/api/meetings/{number}",
        json={"settings": {"waiting_room": True}},
        headers=auth_header(token),
    )

    guests = []
    for i in range(4):
        r = client.post(
            f"/api/meetings/{number}/join",
            json={"display_name": f"Guest {i}", "passcode": meeting.get("passcode")},
        )
        assert r.status_code in (200, 201), r.text
        guests.append(r.json())

    with client.websocket_connect(_ws_url(meeting, host)) as host_sock:
        host_sock.receive_json()
        sockets = []
        try:
            for guest in guests:
                gs = client.websocket_connect(_ws_url(meeting, guest)).__enter__()
                assert gs.receive_json()["type"] == "waiting"
                sockets.append(gs)

            count_sessions.clear()
            host_sock.send_json({"type": "admit-all"})
            for gs in sockets:
                while True:
                    msg = gs.receive_json()
                    if msg["type"] == "admitted":
                        break
            during_admit = len(count_sessions)
        finally:
            for gs in sockets:
                gs.__exit__(None, None, None)

    assert during_admit == 1, (
        f"admitting {len(guests)} guests opened {during_admit} "
        "sessions; the admission write should be one transaction"
    )


def test_denying_a_guest_is_one_transaction(client, count_sessions):
    """Denial used to be two sessions - one for `admission`, one for
    `is_active` - on the same row, leaving a window where a denied guest was
    still counted as present."""
    from app import models

    token, meeting, host = _meeting_with_host(client)
    number = meeting["meeting_number"]
    client.patch(
        f"/api/meetings/{number}",
        json={"settings": {"waiting_room": True}},
        headers=auth_header(token),
    )
    guest = client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": "Unwanted", "passcode": meeting.get("passcode")},
    ).json()

    with client.websocket_connect(_ws_url(meeting, host)) as host_sock:
        host_sock.receive_json()
        with client.websocket_connect(_ws_url(meeting, guest)) as guest_sock:
            assert guest_sock.receive_json()["type"] == "waiting"
            count_sessions.clear()
            host_sock.send_json({"type": "deny", "target": guest["id"]})
            while True:
                msg = guest_sock.receive_json()
                if msg["type"] == "denied":
                    break
            during_deny = len(count_sessions)

    assert during_deny == 1

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(models.Participant, guest["id"])
        assert row.admission == "denied"
        assert row.is_active is False
    finally:
        db.close()
