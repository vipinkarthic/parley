"""Auth smoke tests: health, seeded demo login, and the full OTP signup flow.

The OTP expiry test is the important one for the Postgres cutover. Expiry is a
comparison between ``datetime.now()`` and a value read back out of the
database; if the stored side and the compared side stop agreeing about
timezone, verification breaks for every new signup and nothing else in the
suite would notice.
"""
from datetime import timedelta

from conftest import DEMO_EMAIL, DEMO_PASSWORD, auth_header, signup, unique_email


def test_health(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "parley-api"}


def test_demo_account_is_seeded_and_can_log_in(client):
    """A resume-linked demo has to be clickable without an OTP round trip, so
    the seeded accounts existing is a product requirement, not a convenience."""
    r = client.post(
        "/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"]
    assert body["user"]["email"] == DEMO_EMAIL
    assert body["user"]["avatar_color"].startswith("#")


def test_login_rejects_a_bad_password(client):
    r = client.post(
        "/auth/login", json={"email": DEMO_EMAIL, "password": "not-the-password"}
    )
    assert r.status_code == 401


def test_login_rejects_an_unknown_email(client):
    r = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert r.status_code == 401


def test_me_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_the_token_holder(client, user_token):
    token, user = user_token
    r = client.get("/auth/me", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json()["email"] == user["email"]


def test_me_rejects_a_forged_token(client):
    r = client.get("/auth/me", headers=auth_header("not.a.real.jwt"))
    assert r.status_code == 401


def test_signup_otp_flow_end_to_end(client):
    email = unique_email("signup")
    token, user = signup(client, email, name="Signup Person")
    assert user["email"] == email
    assert user["name"] == "Signup Person"
    # the new account is usable straight away
    r = client.get("/auth/me", headers=auth_header(token))
    assert r.status_code == 200
    # and can log in by password
    r = client.post("/auth/login", json={"email": email, "password": "hunter2222"})
    assert r.status_code == 200


def test_signup_does_not_reveal_that_an_email_is_registered(client):
    # A different status for a known address answers "is this registered?"
    # to anyone who asks.
    email = unique_email("dupe")
    signup(client, email)

    taken = client.post(
        "/auth/signup/request-otp",
        json={"name": "Someone Else", "email": email, "password": "hunter2222"},
    )
    fresh = client.post(
        "/auth/signup/request-otp",
        json={"name": "Nobody", "email": unique_email("free"), "password": "hunter2222"},
    )

    assert taken.status_code == fresh.status_code == 200
    assert set(taken.json()) == set(fresh.json())
    # No code for an address the caller does not own.
    assert taken.json()["dev_code"] is None
    assert fresh.json()["dev_code"]


def test_signup_rejects_a_wrong_code(client):
    email = unique_email("wrongcode")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "Wrong Code", "email": email, "password": "hunter2222"},
    )
    real_code = r.json()["dev_code"]
    bad_code = "000000" if real_code != "000000" else "111111"

    r = client.post("/auth/signup/verify", json={"email": email, "code": bad_code})
    assert r.status_code == 400
    # the real code still works afterwards
    r = client.post("/auth/signup/verify", json={"email": email, "code": real_code})
    assert r.status_code == 200


def test_expired_otp_is_rejected(client, db):
    """Backdate the stored expiry and confirm verification returns 410.

    Uses the application's own clock so the test stays honest whether
    timestamps are naive local time or timezone-aware UTC.
    """
    from app import models
    from app.models import utcnow

    email = unique_email("expired")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "Expired", "email": email, "password": "hunter2222"},
    )
    code = r.json()["dev_code"]

    pending = (
        db.query(models.PendingSignup)
        .filter(models.PendingSignup.email == email)
        .one()
    )
    pending.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()

    r = client.post("/auth/signup/verify", json={"email": email, "code": code})
    assert r.status_code == 410, (
        "expected 410 Gone for an expired OTP - a naive/aware timestamp "
        f"mismatch shows up here first. Got {r.status_code}: {r.text}"
    )


def test_unexpired_otp_is_accepted(client, db):
    """The mirror of the expiry test: a code well within its TTL must verify.

    Without this, a timestamp bug that makes *everything* look expired would
    still pass the test above.
    """
    from app import models
    from app.models import utcnow

    email = unique_email("fresh")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "Fresh", "email": email, "password": "hunter2222"},
    )
    code = r.json()["dev_code"]

    pending = (
        db.query(models.PendingSignup)
        .filter(models.PendingSignup.email == email)
        .one()
    )
    pending.expires_at = utcnow() + timedelta(minutes=9)
    db.commit()

    r = client.post("/auth/signup/verify", json={"email": email, "code": code})
    assert r.status_code == 200, r.text


def test_resend_otp_replaces_the_previous_code(client):
    email = unique_email("resend")
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": "Resend", "email": email, "password": "hunter2222"},
    )
    first = r.json()["dev_code"]

    r = client.post("/auth/signup/resend-otp", json={"email": email})
    assert r.status_code == 200
    second = r.json()["dev_code"]

    if first != second:
        assert (
            client.post(
                "/auth/signup/verify", json={"email": email, "code": first}
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/auth/signup/verify", json={"email": email, "code": second}
        ).status_code
        == 200
    )


def test_change_password(client):
    email = unique_email("changepw")
    token, _ = signup(client, email)
    r = client.post(
        "/auth/change-password",
        json={"current_password": "hunter2222", "new_password": "newpass9999"},
        headers=auth_header(token),
    )
    assert r.status_code == 200
    assert (
        client.post(
            "/auth/login", json={"email": email, "password": "hunter2222"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": email, "password": "newpass9999"}
        ).status_code
        == 200
    )
