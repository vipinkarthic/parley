"""The transport that actually carries the OTP.

The regression this guards shipped to production and was invisible: signup
returned 200 with `email_sent: true` and no code ever arrived. Delivery was
smtplib against Gmail, and the host blocks outbound SMTP, so every send died
with ENETUNREACH after the response had already gone out. Nothing failed
loudly and no test covered delivery, so the only trace was one log line.

These cover the transport choice and the failure paths. They do not send mail:
the API call is stubbed, because a test that needs a real mailbox is a test
nobody runs.
"""
import urllib.error
import urllib.request

import pytest
from app import config
from app.emailer import EmailSendError, send_otp_email


def _use_resend(monkeypatch, capture=None, raises=None):
    """Point the emailer at a stubbed mail API."""
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "EMAIL_TRANSPORT", "resend")
    monkeypatch.setattr(config, "RESEND_API_KEY", "test-key")

    def fake_urlopen(request, timeout=None):
        if raises is not None:
            raise raises
        if capture is not None:
            capture["request"] = request
            capture["timeout"] = timeout

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_a_send_posts_the_code_to_the_mail_api(monkeypatch):
    captured = {}
    _use_resend(monkeypatch, capture=captured)

    assert send_otp_email("someone@example.com", "123456") is True

    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.full_url == config.RESEND_ENDPOINT
    assert request.get_header("Authorization") == "Bearer test-key"
    assert captured["timeout"] == config.EMAIL_TIMEOUT


def test_the_payload_carries_both_bodies_and_the_configured_sender(monkeypatch):
    import json

    captured = {}
    _use_resend(monkeypatch, capture=captured)
    monkeypatch.setattr(config, "EMAIL_FROM", "Parley <noreply@example.com>")

    send_otp_email("someone@example.com", "654321")

    payload = json.loads(captured["request"].data.decode())
    assert payload["from"] == "Parley <noreply@example.com>"
    assert payload["to"] == ["someone@example.com"]
    assert "654321" in payload["text"]
    # The HTML part is what the recipient actually reads, so losing it in
    # translation would be a silent downgrade rather than a failure.
    assert "654321" in payload["html"]


def test_an_unreachable_network_raises_instead_of_reporting_success(monkeypatch):
    """This is the production failure, reproduced.

    ENETUNREACH is what a blocked SMTP port looks like from inside the
    container. Whichever transport hits it, the caller has to be told.
    """
    _use_resend(monkeypatch, raises=OSError(101, "Network is unreachable"))

    with pytest.raises(EmailSendError):
        send_otp_email("someone@example.com", "123456")


def test_an_api_rejection_raises(monkeypatch):
    """A bad key and an unverified sender domain both arrive as an HTTP error."""
    rejection = urllib.error.HTTPError(
        config.RESEND_ENDPOINT, 403, "Forbidden", {}, None
    )
    monkeypatch.setattr(rejection, "read", lambda: b'{"message":"domain not verified"}')
    _use_resend(monkeypatch, raises=rejection)

    with pytest.raises(EmailSendError):
        send_otp_email("someone@example.com", "123456")


def test_the_code_never_rides_in_the_exception(monkeypatch):
    """An error string reaches the client, so it must not carry the secret."""
    _use_resend(monkeypatch, raises=OSError(101, "Network is unreachable"))

    with pytest.raises(EmailSendError) as caught:
        send_otp_email("someone@example.com", "999111")
    assert "999111" not in str(caught.value)


def test_no_transport_falls_back_to_logging_the_code(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", False)
    # False means "no real email was dispatched", which is what lets the dev
    # path hand the code back inline outside production.
    assert send_otp_email("someone@example.com", "123456") is False
