"""Regression guards for the security audit fixes.

Each test here exists because the behaviour it asserts was wrong at some
point, and in one case was fixed and then silently reintroduced: demo account
seeding was removed in Phase 0 and added back by a later commit, so the live
deployment shipped a published password for weeks. A passing suite did not
notice, because nothing asserted the absence.

These are the assertions that would have.
"""
import time

from conftest import auth_header, signup, unique_email


# ---------------------------------------------------------------------------
# C1 - seeded demo accounts with a published password
# ---------------------------------------------------------------------------


def test_demo_accounts_are_not_seeded_unless_asked_for(monkeypatch):
    """The seeder must do nothing without an explicit opt-in.

    Checked against the seeding function directly rather than through the app,
    because the test suite deliberately turns the flag on for its own fixtures
    and the thing under test is the default.
    """
    from app import seed

    monkeypatch.setattr(seed, "SEED_DEMO_ACCOUNTS", False)
    monkeypatch.setattr(seed, "SEED_SAMPLE_DATA", False)

    called = {"n": 0}
    monkeypatch.setattr(
        seed, "seed_demo_accounts", lambda db: called.__setitem__("n", called["n"] + 1)
    )
    seed.seed_database(db=None)
    assert called["n"] == 0, "demo accounts were seeded without SEED_DEMO_ACCOUNTS"


def test_no_demo_password_literal_survives_in_the_source():
    """The password was in the repository, so reading the repository was the
    whole exploit. It must come from the environment now."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    for path in app_dir.rglob("*.py"):
        body = path.read_text(encoding="utf-8")
        assert "demo1234" not in body, f"a demo password literal is back in {path.name}"


def test_turning_demo_accounts_on_without_a_password_is_refused(monkeypatch):
    """Opting in must not silently fall back to a built-in default."""
    import importlib

    monkeypatch.setenv("SEED_DEMO_ACCOUNTS", "true")
    monkeypatch.setenv("DEMO_PASSWORD", "")
    monkeypatch.setenv("APP_ENV", "development")

    from app import config

    try:
        importlib.reload(config)
    except RuntimeError as exc:
        assert "DEMO_PASSWORD" in str(exc)
    else:
        raise AssertionError("config accepted SEED_DEMO_ACCOUNTS with no password")
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# ---------------------------------------------------------------------------
# H2 - "remove participant" was advisory and survived a reconnect
# ---------------------------------------------------------------------------


def _room(client):
    host_token, _ = signup(client, unique_email("sec-host"))
    meeting = client.post(
        "/api/meetings/instant",
        json={"topic": "Sec", "settings": {"waiting_room": False}},
        headers=auth_header(host_token),
    ).json()
    host = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Host"},
        headers=auth_header(host_token),
    ).json()
    guest = client.post(
        f"/api/meetings/{meeting['meeting_number']}/join",
        json={"display_name": "Guest", "passcode": meeting["passcode"]},
    ).json()
    return meeting["meeting_number"], host, guest


def _drain_to_pong(ws, budget=12):
    ws.send_json({"type": "ping"})
    for _ in range(budget):
        if ws.receive_json().get("type") == "pong":
            return


def test_a_removed_participant_cannot_reconnect(client):
    """Removal used to clear is_active and nothing else, so the row still read
    as admitted and the ws_token still matched. The guest simply dialled back
    in with the same credentials and was put straight back in the room."""
    number, host, guest = _room(client)

    with client.websocket_connect(
        f"/ws/meetings/{number}?pid={host['id']}&token={host['ws_token']}"
    ) as hws:
        with client.websocket_connect(
            f"/ws/meetings/{number}?pid={guest['id']}&token={guest['ws_token']}"
        ) as gws:
            _drain_to_pong(hws)
            _drain_to_pong(gws)
            hws.send_json({"type": "remove-peer", "target": guest["id"]})
            _drain_to_pong(hws)

    try:
        with client.websocket_connect(
            f"/ws/meetings/{number}?pid={guest['id']}&token={guest['ws_token']}"
        ) as back:
            back.receive_json()
            raise AssertionError("a removed participant reconnected into the room")
    except AssertionError:
        raise
    except Exception:
        pass  # refused, which is the point


def test_removal_invalidates_the_participant_token(client, db):
    from app import models

    number, host, guest = _room(client)
    with client.websocket_connect(
        f"/ws/meetings/{number}?pid={host['id']}&token={host['ws_token']}"
    ) as hws:
        _drain_to_pong(hws)
        hws.send_json({"type": "remove-peer", "target": guest["id"]})
        _drain_to_pong(hws)

    row = db.get(models.Participant, guest["id"])
    db.refresh(row)
    assert row.admission == "removed"
    assert row.is_active is False
    assert row.ws_token != guest["ws_token"], "the old token still authenticates"


# ---------------------------------------------------------------------------
# H3 - login timing enumerated accounts
# ---------------------------------------------------------------------------


def test_login_costs_the_same_for_a_known_and_an_unknown_address(client):
    """bcrypt only ran when the user existed, so an unknown address answered
    in ~2ms against ~200ms - a 100x oracle that no error message could hide."""
    email = unique_email("timing")
    signup(client, email)

    def best_of(target):
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            client.post(
                "/auth/login", json={"email": target, "password": "wrong-password-here"}
            )
            best = min(best, time.perf_counter() - started)
        return best

    known = best_of(email)
    unknown = best_of("definitely-not-registered@example.com")

    # Generous: the point is that the unknown path is no longer ~100x faster.
    assert unknown > known / 3, (
        f"unknown address answered far faster ({unknown * 1000:.0f}ms vs "
        f"{known * 1000:.0f}ms), which enumerates accounts"
    )


# ---------------------------------------------------------------------------
# H4 - nothing could revoke an issued token
# ---------------------------------------------------------------------------


def test_changing_a_password_revokes_tokens_issued_before_it(client):
    """A user who changes their password because they think they were
    compromised did not actually lock the attacker out: the old token stayed
    valid until it expired, which was a week."""
    email = unique_email("revoke")
    token, _ = signup(client, email, password="original-pw-1234")

    assert client.get("/auth/me", headers=auth_header(token)).status_code == 200

    time.sleep(1.1)  # iat has whole-second resolution
    changed = client.post(
        "/auth/change-password",
        json={
            "current_password": "original-pw-1234",
            "new_password": "replacement-pw-5678",
        },
        headers=auth_header(token),
    )
    assert changed.status_code == 200, changed.text

    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401

    fresh = client.post(
        "/auth/login", json={"email": email, "password": "replacement-pw-5678"}
    ).json()["token"]
    assert client.get("/auth/me", headers=auth_header(fresh)).status_code == 200


# ---------------------------------------------------------------------------
# M2 / M3 - CORS and security headers
# ---------------------------------------------------------------------------


def test_an_arbitrary_vercel_origin_is_not_trusted(client):
    """The allow-list regex was `https://.*\\.vercel\\.app`, so anyone could
    deploy to Vercel and get an origin the API trusted with credentials."""
    r = client.options(
        "/api/meetings",
        headers={
            "Origin": "https://totally-unrelated-attacker.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") != (
        "https://totally-unrelated-attacker.vercel.app"
    )


def test_responses_carry_security_headers(client):
    r = client.get("/healthz")
    for header in (
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy",
    ):
        assert header in r.headers, f"{header} is missing"
    assert r.headers["x-content-type-options"] == "nosniff"
    # The invite link can carry a passcode, so the URL must not travel onward.
    assert r.headers["referrer-policy"] == "no-referrer"


# ---------------------------------------------------------------------------
# M12 - the signalling socket accepted arbitrarily large frames
# ---------------------------------------------------------------------------


def test_an_oversized_signalling_message_closes_the_socket(client):
    """uvicorn would hand up a 16 MiB frame and json.loads would parse it."""
    from app.ws import MAX_MESSAGE_BYTES

    number, host, _ = _room(client)
    with client.websocket_connect(
        f"/ws/meetings/{number}?pid={host['id']}&token={host['ws_token']}"
    ) as ws:
        _drain_to_pong(ws)
        ws.send_json({"type": "chat", "text": "x" * (MAX_MESSAGE_BYTES + 1)})
        try:
            for _ in range(5):
                ws.receive_json()
        except Exception:
            return
        raise AssertionError("an oversized frame was accepted")


# ---------------------------------------------------------------------------
# Directory privacy and the public meeting view
# ---------------------------------------------------------------------------


def test_the_public_meeting_view_does_not_leak_the_host_identity(client):
    """GET /api/meetings/{n} is unauthenticated by design, and used to return
    the host's full user record - email address and permanent PMI included."""
    host_email = unique_email("host-pii")
    token, _ = signup(client, host_email)
    meeting = client.post(
        "/api/meetings/instant", json={"topic": "T"}, headers=auth_header(token)
    ).json()

    body = client.get(f"/api/meetings/{meeting['meeting_number']}")
    assert host_email not in body.text
    host = body.json()["host"]
    assert "email" not in host
    assert "pmi" not in host
    assert body.json()["passcode"] is None
