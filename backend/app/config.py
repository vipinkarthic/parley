"""Runtime configuration read from environment variables."""
import logging
import os
from pathlib import Path

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

# --- Database -------------------------------------------------------------
# Neon hands out `postgresql://...`; SQLAlchemy needs the driver named, and
# some hosts still emit the legacy `postgres://` scheme. Normalise both rather
# than making the operator get the URL exactly right.
_DEFAULT_SQLITE_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'parley.db'}"


def _normalise_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _normalise_database_url(os.getenv("DATABASE_URL", "").strip())

if not DATABASE_URL:
    if IS_PRODUCTION:
        # Falling back to SQLite here would put the database on Render's
        # ephemeral disk, which is silently wiped on every deploy - the exact
        # failure this phase exists to remove. Refuse to boot instead.
        raise RuntimeError(
            "DATABASE_URL is unset. Set the Neon pooled connection string "
            "before running with APP_ENV=production."
        )
    DATABASE_URL = _DEFAULT_SQLITE_URL
    logger.warning(
        "DATABASE_URL is unset - falling back to a local SQLite file. Fine for "
        "an offline test run; set the Neon URL for anything else."
    )

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# Neon's pooled endpoint is PgBouncer in transaction mode, which cannot carry
# server-side prepared statements between transactions; psycopg3 creates them
# automatically after a few executions. Sizes are deliberate rather than
# defaulted: Render's free tier runs one instance.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "5"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "280"))

# --- Media plane (Phase 4) -------------------------------------------------
# The mesh is O(n^2) in uploads, so the ceiling is a client CPU and uplink
# limit, not a server one. ROOM_CAP is the number the server refuses to seat
# past; VIDEO_BUDGET is how many remote videos a client subscribes to at once.
#
# ROOM_CAP is measured, not guessed. Ramped 2->12 real headless Chrome peers
# on a 20-core i7-12700H (backend/tools/loadtest.py, 2026-09-11):
#
#   peers   up/peer   sent      CPU/peer   quality limited by
#   6       845 kbps  240p@20   53%        none
#   8       500 kbps  178p@13   60%        none
#   10      490 kbps  173p@13   83%        none
#   12      486 kbps  166p@14   98%        bandwidth on 2 of 132 streams
#
# 10 is the last rung with headroom. At 12 a participant needs essentially a
# full CPU core and the first bandwidth limitation appears; at 10 there is
# still margin on both. Video at the cap is ~180p - small, and the README
# says so rather than implying otherwise.
ROOM_CAP = int(os.getenv("ROOM_CAP", "10"))
VIDEO_BUDGET = int(os.getenv("VIDEO_BUDGET", "5"))

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

# --- WebRTC ICE -----------------------------------------------------------
# STUN only tells a peer its public address; it does not carry media. Behind
# symmetric NAT or a corporate firewall there is no direct path to discover, so
# without a TURN relay those peers cannot connect *at all* - which is a
# correctness bug, not a quality-of-service one.
#
# Served to the browser by GET /api/ice rather than baked into the frontend
# bundle: NEXT_PUBLIC_* is inlined at build time, so a credential rotation
# would otherwise mean a Vercel rebuild.
#
# The defaults are Open Relay's public endpoint, kept as a placeholder that
# documents the shape and keeps the relay code path live. It does NOT work -
# see the warning below, and set TURN_URLS / TURN_USERNAME / TURN_CREDENTIAL to
# a real account. These values are not secrets: they reach the browser by
# construction, and anything that reaches the browser is extractable.
def _csv(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


STUN_URLS = _csv(
    "STUN_URLS",
    "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302",
)
TURN_URLS = _csv(
    "TURN_URLS",
    "turn:openrelay.metered.ca:80,"
    "turn:openrelay.metered.ca:443,"
    "turns:openrelay.metered.ca:443?transport=tcp",
)
TURN_USERNAME = os.getenv("TURN_USERNAME", "openrelayproject")
TURN_CREDENTIAL = os.getenv("TURN_CREDENTIAL", "openrelayproject")

# Pre-gathering a couple of candidates shaves a round trip off the first
# connection without holding a relay allocation open for every idle tab.
ICE_CANDIDATE_POOL_SIZE = int(os.getenv("ICE_CANDIDATE_POOL_SIZE", "2"))

_PLACEHOLDER_TURN_HOST = "openrelay.metered.ca"
_PLACEHOLDER_TURN_USERNAME = "openrelayproject"

# Whether TURN is still the known-dead placeholder rather than a real relay.
TURN_IS_PLACEHOLDER = TURN_USERNAME == _PLACEHOLDER_TURN_USERNAME or any(
    _PLACEHOLDER_TURN_HOST in url for url in TURN_URLS
)

if TURN_IS_PLACEHOLDER:
    # Measured 2026-09-10, not assumed. Open Relay's public endpoint issues a
    # 401 challenge and then refuses every Allocate with 400 Bad Request - and
    # it does so identically for the documented credentials, a deliberately
    # wrong password and a nonexistent user, so it is not evaluating
    # credentials at all. Its :443 TLS certificate also does not match its own
    # hostname, so the `turns:` entry cannot be used by a browser either.
    #
    # A warning rather than a hard failure: unlike a missing JWT_SECRET, this
    # degrades connectivity instead of compromising it, and refusing to boot
    # would take the whole demo down to protest a relay - which is worse than
    # running without one.
    logger.warning(
        "TURN is the Open Relay public placeholder, which was measured to "
        "refuse every allocation. There is effectively NO relay: peers behind "
        "symmetric NAT or a restrictive firewall will fail to connect. Set "
        "TURN_URLS, TURN_USERNAME and TURN_CREDENTIAL to a real account."
    )
