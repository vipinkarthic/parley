"""Runtime configuration read from environment variables."""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("parley")

# Render sets RENDER=true on every service, so a deploy is treated as
# production even if APP_ENV was never set. Local dev stays development.
APP_ENV = (
    os.getenv("APP_ENV", "").strip().lower()
    or ("production" if os.getenv("RENDER") else "development")
)
IS_PRODUCTION = APP_ENV == "production"

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

SEED_SAMPLE_DATA = os.getenv("SEED_SAMPLE_DATA", "false").lower() in (
    "1",
    "true",
    "yes",
)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]

# A known secret means anyone can forge a token, so production refuses to boot
# without a real one rather than logging a warning nobody reads. Local dev
# still works with no configuration at all.
_DEV_JWT_SECRET = "dev-secret-change-me-in-production"
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()

if not JWT_SECRET or JWT_SECRET == _DEV_JWT_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError(
            "JWT_SECRET is unset or still the development default. Set a long "
            "random JWT_SECRET before running with APP_ENV=production."
        )
    JWT_SECRET = _DEV_JWT_SECRET
    logger.warning(
        "JWT_SECRET is the built-in development default - fine locally, but "
        "production will refuse to start without a real one."
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "168"))

OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
# No default sender: it is a personal mailbox, not app configuration.
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").replace(" ", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Parley")
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "15"))

# Both halves are needed to authenticate to SMTP; with only one, sending would
# fail at delivery time instead of falling back to the dev OTP path.
EMAIL_ENABLED = bool(SMTP_USER and SMTP_PASS)
