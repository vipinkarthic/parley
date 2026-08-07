"""Runtime configuration read from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()

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

_DEFAULT_JWT_SECRET = "dev-secret-change-me-in-production"
JWT_SECRET = os.getenv("JWT_SECRET", _DEFAULT_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "168"))

if JWT_SECRET == _DEFAULT_JWT_SECRET:
    import logging
    logging.getLogger("zoomclone").warning(
        "JWT_SECRET is the built-in default - set a strong JWT_SECRET env var in "
        "production or tokens can be forged."
    )

OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "10"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "vipinkarthic17112005@gmail.com")
SMTP_PASS = os.getenv("SMTP_PASS", "").replace(" ", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Zoom Clone")
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "15"))

EMAIL_ENABLED = bool(SMTP_PASS)
