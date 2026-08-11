"""Test fixtures.

The suite is deliberately engine-agnostic: it points the application's own
engine at whatever ``TEST_DATABASE_URL`` names (a throwaway SQLite file by
default) and never touches the development database. Running the identical
tests against SQLite and then against Postgres is what makes them a cutover
check rather than a one-off.

    pytest                                    # SQLite
    TEST_DATABASE_URL=postgresql+psycopg://... pytest    # Postgres
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Set before any app module is imported: config.py reads the environment at
# import time, and load_dotenv() will not override a key already present.
os.environ["APP_ENV"] = "development"
os.environ["SEED_SAMPLE_DATA"] = "false"
os.environ["JWT_SECRET"] = "test-secret-not-used-anywhere-real"
os.environ["FRONTEND_URL"] = "http://testserver.example.com"
# Empty credentials force EMAIL_ENABLED=False, so the OTP comes back in the
# response body and no test can ever send real mail.
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASS"] = ""

_TMP_DB = Path(tempfile.gettempdir()) / "parley_test.db"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_TMP_DB}"
# database.py reads DATABASE_URL once at import; setting it here means the app
# builds its own engine against the test database, so code paths that grab
# SessionLocal directly (ws.py, main.py) are covered too.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

IS_POSTGRES = TEST_DATABASE_URL.startswith("postgres")


def _install_test_engine():
    """Point the application's engine at the test database.

    ``database.py`` may or may not honour DATABASE_URL yet (it does after the
    Postgres cutover, it did not before), so rebind explicitly. Modules that
    did ``from .database import SessionLocal`` captured the object at import
    time and need rebinding by name; ``get_db`` resolves the module global at
    call time and follows automatically.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database

    kwargs = {"future": True}
    if TEST_DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True

    engine = create_engine(TEST_DATABASE_URL, **kwargs)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    database.engine = engine
    database.SessionLocal = session_factory

    from app import main, ws

    main.engine = engine
    main.SessionLocal = session_factory
    ws.SessionLocal = session_factory

    return engine, session_factory


ENGINE, SESSION_FACTORY = _install_test_engine()


@pytest.fixture(scope="session", autouse=True)
def _fresh_schema():
    """Build the schema by running the real migrations against an empty database.

    Deliberately not ``Base.metadata.create_all()``. Using the migrations here
    means every test run is also a test that ``alembic upgrade head`` works
    from nothing - which is the actual Phase 1 acceptance criterion, and the
    thing that would otherwise only ever be exercised by hand against Neon.
    """
    from sqlalchemy import text

    from alembic import command
    from alembic.config import Config

    from app.database import Base
    from app import models  # noqa: F401  (registers the mappers)

    # Start from genuinely nothing, including any leftover version bookkeeping.
    Base.metadata.drop_all(bind=ENGINE)
    with ENGINE.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(cfg, "head")

    yield

    Base.metadata.drop_all(bind=ENGINE)
    with ENGINE.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture(scope="session")
def client(_fresh_schema):
    """TestClient with the app's lifespan run (which seeds the demo accounts)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The auth limiter is process-global; without this, the 11th login in a
    run fails for reasons that have nothing to do with the test."""
    from app import ratelimit

    ratelimit._hits.clear()
    yield
    ratelimit._hits.clear()


@pytest.fixture
def db():
    """A raw session for assertions that need to look at stored rows."""
    session = SESSION_FACTORY()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

DEMO_EMAIL = "demo1@parley.app"
DEMO_PASSWORD = "demo1234"

_counter = {"n": 0}


def unique_email(prefix: str = "user") -> str:
    _counter["n"] += 1
    return f"{prefix}{_counter['n']}-{os.getpid()}@example.com"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signup(client, email: str, name: str = "Test User", password: str = "hunter2222"):
    """Full signup: request an OTP, read it out of the dev response, verify.

    Returns (token, user dict).
    """
    r = client.post(
        "/auth/signup/request-otp",
        json={"name": name, "email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    assert code, "dev_code should be present when email is disabled"

    r = client.post("/auth/signup/verify", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["user"]


@pytest.fixture
def user_token(client):
    """A freshly signed-up user, isolated from the demo accounts."""
    token, user = signup(client, unique_email("host"))
    return token, user
