"""Regression guards for the security audit fixes.

Demo seeding was removed once and silently added back, and nothing caught it.
"""
import time

from conftest import auth_header, signup, unique_email


# Seeded demo accounts with a published password


def test_demo_accounts_are_not_seeded_unless_asked_for(monkeypatch):
    """Checked directly, since the suite turns the flag on for its fixtures."""
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
    """Reading the repository was the whole exploit."""
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    for path in app_dir.rglob("*.py"):
        body = path.read_text(encoding="utf-8")
        assert "demo1234" not in body, f"a demo password literal is back in {path.name}"


def test_turning_demo_accounts_on_without_a_password_is_refused(monkeypatch):
    """Opting in must not fall back to a built in default."""
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


# Removing a participant was advisory and survived a reconnect


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
    # Everything queued before the ping arrives before the pong.
    ws.send_json({"type": "ping"})
    for _ in range(budget):
        if ws.receive_json().get("type") == "pong":
            return


def test_a_removed_participant_cannot_reconnect(client):
    """Clearing is_active left a working token on an admitted row."""
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


# Login timing enumerated accounts


def test_login_costs_the_same_for_a_known_and_an_unknown_address(client):
    """bcrypt only ran for a real account, so the gap was 100x."""
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

    # Generous, since the point is only that the gap is gone.
    assert unknown > known / 3, (
        f"unknown address answered far faster ({unknown * 1000:.0f}ms vs "
        f"{known * 1000:.0f}ms), which enumerates accounts"
    )


# Nothing could revoke an issued token


def test_changing_a_password_revokes_tokens_issued_before_it(client):
    """A password change did not lock out a stolen token."""
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


# CORS and security headers


def test_an_arbitrary_vercel_origin_is_not_trusted(client):
    """Anyone can deploy to Vercel, so a wildcard over it trusts anyone."""
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


# The signalling socket accepted arbitrarily large frames


def test_an_oversized_signalling_message_closes_the_socket(client):
    """uvicorn allows 16 MiB and json.loads would parse all of it."""
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


# Directory privacy and the public meeting view


def test_the_public_meeting_view_does_not_leak_the_host_identity(client):
    """This route is unauthenticated and returned the host's full record."""
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


# Signup must refuse rather than hand the OTP back


def test_production_without_a_mailer_refuses_signup(client, monkeypatch):
    """Only signup needs SMTP, so the rest of the service stays up."""
    from app import config

    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "EMAIL_ENABLED", False)

    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "X", "email": unique_email("nomail"), "password": "hunter2222"},
    )
    assert r.status_code == 503
    assert "dev_code" not in r.text

    resend = client.post(
        "/auth/signup/resend-otp", json={"email": unique_email("nomail")}
    )
    assert resend.status_code == 503


def test_the_rest_of_the_api_survives_a_missing_mailer(client, monkeypatch):
    """Refusing to boot over a signup dependency took meetings down with it."""
    from app import config

    token, _ = signup(client, unique_email("survives"))
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "EMAIL_ENABLED", False)

    assert client.get("/healthz").status_code == 200
    assert client.get("/auth/me", headers=auth_header(token)).status_code == 200
    created = client.post(
        "/api/meetings/instant", json={"topic": "Still up"}, headers=auth_header(token)
    )
    assert created.status_code == 201
    number = created.json()["meeting_number"]
    joined = client.post(
        f"/api/meetings/{number}/join",
        json={"display_name": "Guest", "passcode": created.json()["passcode"]},
    )
    assert joined.status_code == 201


def test_the_code_never_rides_in_a_production_response(client, monkeypatch):
    """A mailer that is configured but failing must not fall back to this."""
    from app import config

    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr("app.routers.auth.send_otp_email", lambda *a, **k: True)

    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "X", "email": unique_email("prod"), "password": "hunter2222"},
    )
    assert r.status_code == 200
    assert r.json()["dev_code"] is None
