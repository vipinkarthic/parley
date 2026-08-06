"""OTP email delivery via SMTP, with a dev fallback.

When SMTP credentials are configured (SMTP_PASS set), the OTP is emailed from
the configured Gmail account. Otherwise the code is logged to the server console
so the app remains fully usable in development without email setup.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config

logger = logging.getLogger("zoomclone.email")


class EmailSendError(Exception):
    """Raised when real email delivery is configured but the send failed."""


def _build_message(to_email: str, code: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your Zoom Clone verification code"
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(
        f"Your Zoom Clone verification code is: {code}\n\n"
        f"It expires in {config.OTP_TTL_MINUTES} minutes. "
        f"If you didn't request this, you can ignore this email."
    )
    msg.add_alternative(
        f"""
        <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto;padding:24px">
          <h2 style="color:#232333;margin:0 0 8px">Verify your email</h2>
          <p style="color:#666484;margin:0 0 24px">
            Enter this code to finish creating your Zoom Clone account.
          </p>
          <div style="font-size:34px;font-weight:700;letter-spacing:8px;color:#0B5CFF;
                      background:#EEF3FF;border-radius:12px;padding:18px;text-align:center">
            {code}
          </div>
          <p style="color:#8B8B9A;font-size:13px;margin:24px 0 0">
            This code expires in {config.OTP_TTL_MINUTES} minutes.
          </p>
        </div>
        """,
        subtype="html",
    )
    return msg


def send_otp_email(to_email: str, code: str) -> bool:
    """Send the OTP.

    Returns True if a real email was dispatched, False in dev mode (no SMTP
    credentials — the code is logged instead). Raises ``EmailSendError`` when
    delivery is configured but fails, so the caller can surface a clean error
    rather than leaking a 500 (and never fall back to exposing the code).
    """
    if not config.EMAIL_ENABLED:
        logger.warning(
            "[DEV] Email not configured — OTP for %s is: %s", to_email, code
        )
        print(f"\n>>> [DEV OTP] {to_email} -> {code}\n", flush=True)
        return False

    msg = _build_message(to_email, code)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT
        ) as server:
            server.starttls(context=context)
            server.login(config.SMTP_USER, config.SMTP_PASS)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP auth failed for %s: %s", config.SMTP_USER, exc)
        raise EmailSendError(
            "Email sign-in was rejected. Check the Gmail App Password."
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        logger.error("SMTP send to %s failed: %s", to_email, exc)
        raise EmailSendError(
            "We couldn't send the verification email. Please try again."
        ) from exc

    logger.info("OTP email sent to %s", to_email)
    return True
