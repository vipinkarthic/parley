"""The auth limiter, which is the only thing standing between the login form
and an unbounded password guess.

`conftest` clears the limiter between tests, so these have to reach past the
public endpoints in a couple of places to exercise the window itself. The
limits are read from the router rather than retyped, so tuning them there
does not silently turn these into tests of nothing.
"""
import pytest

from app.routers.auth import (
    _LOGIN_LIMIT,
    _LOGIN_WINDOW,
    _OTP_LIMIT,
    _OTP_WINDOW,
)
from conftest import DEMO_EMAIL, DEMO_PASSWORD, auth_header, unique_email


def _login(client, email, password="wrong-password"):
    return client.post("/auth/login", json={"email": email, "password": password})


def _request_otp(client, email):
    return client.post(
        "/auth/signup/request-otp",
        json={"name": "Rate Limited", "email": email, "password": "hunter2222"},
    )


# ---------------------------------------------------------------------------
# the limiter itself
# ---------------------------------------------------------------------------

def test_the_limiter_allows_up_to_the_limit(client):
    from app import ratelimit

    assert all(ratelimit.allow("k", 3, 60) for _ in range(3))
    assert not ratelimit.allow("k", 3, 60)


def test_the_limiter_is_keyed(client):
    from app import ratelimit

    for _ in range(3):
        ratelimit.allow("a", 3, 60)
    assert not ratelimit.allow("a", 3, 60)
    assert ratelimit.allow("b", 3, 60), "a different key must have its own budget"


def test_the_window_slides(client, monkeypatch):
    """An old hit must fall out rather than counting forever."""
    from app import ratelimit

    clock = {"t": 1_000.0}
    monkeypatch.setattr(ratelimit.time, "time", lambda: clock["t"])

    for _ in range(3):
        assert ratelimit.allow("windowed", 3, 60)
    assert not ratelimit.allow("windowed", 3, 60)

    clock["t"] += 61
    assert ratelimit.allow("windowed", 3, 60), "the window never expired"


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def test_repeated_bad_logins_are_eventually_refused(client):
    email = DEMO_EMAIL
    for _ in range(_LOGIN_LIMIT):
        assert _login(client, email).status_code == 401

    blocked = _login(client, email)
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json()["detail"]


def test_the_login_limit_is_per_email(client):
    for _ in range(_LOGIN_LIMIT):
        _login(client, DEMO_EMAIL)
    assert _login(client, DEMO_EMAIL).status_code == 429

    other = _login(client, unique_email("ratelimit-other"))
    assert other.status_code != 429, "one account's guesses locked out another"


def test_the_limit_survives_case_and_whitespace(client):
    """Otherwise the counter resets by typing the address differently."""
    for _ in range(_LOGIN_LIMIT):
        _login(client, DEMO_EMAIL)

    assert _login(client, f"  {DEMO_EMAIL.upper()}  ").status_code == 429


def test_a_throttled_account_still_has_the_right_password_refused(client):
    """The limiter has to bite before the password check, or it is decorative."""
    for _ in range(_LOGIN_LIMIT):
        _login(client, DEMO_EMAIL)

    assert _login(client, DEMO_EMAIL, DEMO_PASSWORD).status_code == 429


def test_the_limiter_lets_a_real_login_through_once_the_window_passes(client, monkeypatch):
    from app import ratelimit

    clock = {"t": 2_000.0}
    monkeypatch.setattr(ratelimit.time, "time", lambda: clock["t"])

    for _ in range(_LOGIN_LIMIT):
        _login(client, DEMO_EMAIL)
    assert _login(client, DEMO_EMAIL, DEMO_PASSWORD).status_code == 429

    clock["t"] += _LOGIN_WINDOW + 1
    ok = _login(client, DEMO_EMAIL, DEMO_PASSWORD)
    assert ok.status_code == 200, ok.text
    assert ok.json()["token"]


# ---------------------------------------------------------------------------
# OTP email
# ---------------------------------------------------------------------------

def test_otp_requests_are_capped(client):
    """Otherwise the signup form is an open relay pointed at someone's inbox."""
    email = unique_email("otp-flood")
    for _ in range(_OTP_LIMIT):
        assert _request_otp(client, email).status_code == 200

    blocked = _request_otp(client, email)
    assert blocked.status_code == 429


def test_the_otp_cap_covers_resend_too(client):
    """Resend shares the budget; a separate one would just move the hole."""
    email = unique_email("otp-resend")
    for _ in range(_OTP_LIMIT):
        assert _request_otp(client, email).status_code == 200

    resent = client.post("/auth/signup/resend-otp", json={"email": email})
    assert resent.status_code == 429


def test_the_otp_cap_is_per_address(client):
    first = unique_email("otp-a")
    for _ in range(_OTP_LIMIT):
        _request_otp(client, first)
    assert _request_otp(client, first).status_code == 429

    assert _request_otp(client, unique_email("otp-b")).status_code == 200


def test_wrong_codes_burn_the_signup_down(client):
    """A capped OTP is only strong if the code cannot be brute-forced instead."""
    from app import config

    email = unique_email("otp-guess")
    assert _request_otp(client, email).status_code == 200

    for _ in range(config.OTP_MAX_ATTEMPTS):
        r = client.post("/auth/signup/verify", json={"email": email, "code": "000000"})
        assert r.status_code == 400, r.text

    dead = client.post("/auth/signup/verify", json={"email": email, "code": "000000"})
    assert dead.status_code == 429
    assert "start again" in dead.json()["detail"].lower()
