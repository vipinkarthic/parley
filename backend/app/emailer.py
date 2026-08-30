"""OTP email delivery, over an HTTPS API or SMTP, with a dev fallback.

Transport is chosen in config: the Resend API when `RESEND_API_KEY` is set,
SMTP when Gmail credentials are, and otherwise a dev path that logs the code so
the app stays usable with no mail setup at all.

The API path exists because most PaaS hosts block outbound SMTP. Render refuses
ports 25, 465 and 587, so smtplib fails with ENETUNREACH before it can
authenticate and no App Password will help. Port 443 is open.
"""
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

from . import config

logger = logging.getLogger("parley.email")


class EmailSendError(Exception):
    """Raised when real email delivery is configured but the send failed."""


def _build_message(to_email: str, code: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your Parley verification code"
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(
        f"Your Parley verification code is: {code}\n\n"
        f"It expires in {config.OTP_TTL_MINUTES} minutes. "
        f"If you didn't request this, you can ignore this email."
    )
    msg.add_alternative(
        f"""
        <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;padding:24px">
          <h2 style="color:#1C2624;margin:0 0 8px">Verify your email</h2>
          <p style="color:#5A6866;margin:0 0 24px">
            Enter this code to finish creating your Parley account.
          </p>
          <div style="font-size:34px;font-weight:700;letter-spacing:8px;color:#0E7C74;
                      background:#E6F4F2;border-radius:12px;padding:18px;text-align:center">
            {code}
          </div>
          <p style="color:#8A9694;font-size:13px;margin:24px 0 0">
            This code expires in {config.OTP_TTL_MINUTES} minutes.
          </p>
        </div>
        """,
        subtype="html",
    )
    return msg


def _build_existing_account_message(to_email: str) -> EmailMessage:
    """How the owner of the address learns what happened."""
    msg = EmailMessage()
    msg["Subject"] = "You already have a Parley account"
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(
        "Someone just tried to create a Parley account with this email "
        "address, but you already have one.\n\n"
        "If that was you, sign in instead. No new account is needed. "
        "If it wasn't, you can safely ignore this email; nobody was told "
        "whether this address is registered."
    )
    return msg


def send_existing_account_notice(to_email: str) -> bool:
    """Best effort. A failure must not change what signup returns."""
    if not config.EMAIL_ENABLED:
        logger.info("[DEV] signup attempted on an existing account: %s", to_email)
        return False
    try:
        _deliver(_build_existing_account_message(to_email))
    except Exception as exc:
        logger.error("existing-account notice to %s failed: %s", to_email, exc)
        return False
    return True


def _part(msg: EmailMessage, subtype: str) -> str | None:
    """The body of one MIME subtype, or None when the message has no such part."""
    part = msg.get_body(preferencelist=(subtype,))
    return part.get_content() if part is not None else None


def _deliver_via_resend(msg: EmailMessage) -> None:
    """POST the message to Resend.

    The sender is `EMAIL_FROM` rather than the address `_build_message` set,
    because an API sender has to be one the account is allowed to send from and
    that is unrelated to whichever mailbox SMTP would have used.
    """
    payload = {
        "from": config.EMAIL_FROM,
        "to": [msg["To"]],
        "subject": msg["Subject"],
    }
    text = _part(msg, "plain")
    html = _part(msg, "html")
    if text:
        payload["text"] = text
    if html:
        payload["html"] = html

    request = urllib.request.Request(
        config.RESEND_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {config.RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.EMAIL_TIMEOUT):
        pass


def _deliver_via_smtp(msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP(
        config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT
    ) as server:
        server.starttls(context=context)
        server.login(config.SMTP_USER, config.SMTP_PASS)
        server.send_message(msg)


def _deliver(msg: EmailMessage) -> None:
    """Send by whichever transport is configured. Raises on failure."""
    if config.EMAIL_TRANSPORT == "resend":
        _deliver_via_resend(msg)
    else:
        _deliver_via_smtp(msg)


def send_otp_email(to_email: str, code: str) -> bool:
    """Send the OTP.

    Returns True if a real email was dispatched, False in dev mode (no SMTP
    credentials - the code is logged instead). Raises ``EmailSendError`` when
    delivery is configured but fails, so the caller can surface a clean error
    rather than leaking a 500 (and never fall back to exposing the code).
    """
    if not config.EMAIL_ENABLED:
        logger.warning(
            "[DEV] Email not configured - OTP for %s is: %s", to_email, code
        )
        print(f"\n>>> [DEV OTP] {to_email} -> {code}\n", flush=True)
        return False

    try:
        _deliver(_build_message(to_email, code))
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP auth failed for %s: %s", config.SMTP_USER, exc)
        raise EmailSendError(
            "Email sign-in was rejected. Check the Gmail App Password."
        ) from exc
    except urllib.error.HTTPError as exc:
        # Resend puts the reason in the body, and it is the only thing that
        # distinguishes a bad key from an unverified sender domain.
        detail = exc.read().decode("utf-8", "replace")[:200]
        logger.error(
            "mail API rejected %s: %s %s", to_email, exc.code, detail
        )
        raise EmailSendError(
            "We couldn't send the verification email. Please try again."
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        logger.error(
            "%s send to %s failed: %s", config.EMAIL_TRANSPORT, to_email, exc
        )
        raise EmailSendError(
            "We couldn't send the verification email. Please try again."
        ) from exc

    logger.info("OTP email sent to %s via %s", to_email, config.EMAIL_TRANSPORT)
    return True
