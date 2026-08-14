"""Health endpoints, request ids, and OTP delivery that cannot fail a signup."""
from conftest import unique_email


class _DeadEngine:
    """Stands in for an engine whose database is unreachable."""

    def connect(self):
        raise RuntimeError("could not connect to server")


# --- health ------------------------------------------------------------


def test_healthz_is_liveness_only(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["service"] == "parley-api"


def test_healthz_survives_an_unreachable_database(client, monkeypatch):
    """The point of the endpoint.

    The keepalive from tle-machine hits this every ten minutes. Neon's free
    plan meters compute-hours and scales to zero after ~5 min idle, so if this
    opened a connection it would hold the database awake around the clock to
    keep Render's instance warm - and worse, a database blip would fail
    Render's own health check and take the API down with it.
    """
    from app import main

    monkeypatch.setattr(main, "engine", _DeadEngine())
    assert client.get("/healthz").status_code == 200


def test_readyz_reports_503_when_the_database_is_unreachable(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "engine", _DeadEngine())
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["database"] == "unreachable"
    # An unauthenticated endpoint must not echo a driver error: those can
    # carry the connection string.
    assert "connect to server" not in r.text


def test_readyz_is_ok_against_a_live_database(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


def test_the_original_health_route_is_unchanged(client):
    """Render's deployed service has its health check pointed at "/"."""
    assert client.get("/").json() == {"status": "ok", "service": "parley-api"}


# --- request ids -------------------------------------------------------


def test_every_response_carries_a_request_id(client):
    first = client.get("/healthz").headers["X-Request-ID"]
    second = client.get("/healthz").headers["X-Request-ID"]
    assert first and second and first != second


def test_an_inbound_request_id_is_honoured(client):
    """So a trace survives a proxy in front of the API."""
    r = client.get("/healthz", headers={"X-Request-ID": "trace-me-123"})
    assert r.headers["X-Request-ID"] == "trace-me-123"


def test_an_oversized_request_id_is_truncated(client):
    r = client.get("/healthz", headers={"X-Request-ID": "x" * 500})
    assert len(r.headers["X-Request-ID"]) == 64


def test_a_blank_request_id_is_replaced(client):
    r = client.get("/healthz", headers={"X-Request-ID": "   "})
    assert r.headers["X-Request-ID"].strip()


# --- OTP delivery ------------------------------------------------------


def test_smtp_being_down_no_longer_fails_signup(client, monkeypatch):
    """This used to be a 502.

    Signup blocked on Gmail's SMTP round trip, so signup latency *was* Gmail's
    latency - and a send failure rejected the whole signup even though the
    pending row was already committed and a resend would have worked.
    """
    from app import config
    from app.emailer import EmailSendError
    from app.routers import auth as auth_router

    monkeypatch.setattr(config, "EMAIL_ENABLED", True)

    def boom(email, code):
        raise EmailSendError("smtp is down")

    monkeypatch.setattr(auth_router, "send_otp_email", boom)

    email = unique_email("smtpdown")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "SMTP Down", "email": email, "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["email_sent"] is True
    # Never leak the code when real delivery is configured, even on failure.
    assert r.json()["dev_code"] is None

    # And the signup is still recoverable, which is what makes deferring the
    # send acceptable rather than merely faster.
    assert client.post("/auth/signup/resend-otp", json={"email": email}).status_code == 200


def test_dev_mode_still_returns_the_code_inline(client):
    """The dev path only writes to the log, so it is not deferred - the code
    has to be there by the time the developer looks for it."""
    email = unique_email("devmode")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "Dev Mode", "email": email, "password": "password123"},
    )
    assert r.json()["email_sent"] is False
    assert r.json()["dev_code"] and len(r.json()["dev_code"]) == 6
