"""SQLAlchemy engine, session factory, and declarative base.

The engine is built from ``DATABASE_URL`` (Neon's *pooled* connection string in
production). Pool settings are chosen rather than defaulted, because two Neon
behaviours make the defaults wrong:

``pool_pre_ping``
    Neon scales compute to zero after roughly five minutes idle. The first
    request after that finds a pooled connection whose server is gone; without
    a pre-ping it surfaces as a 500 to whoever clicked the demo link first.

``pool_recycle``
    Belt and braces for the same problem - a connection older than the idle
    timeout is discarded rather than tested.

``prepare_threshold=None``
    Neon's pooled endpoint is PgBouncer in transaction mode. psycopg3 starts
    creating server-side prepared statements after a few executions of the same
    query, and those do not survive being handed a different backend
    connection mid-session. Disabling them trades a negligible amount of
    planning time for not breaking under the pooler.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import (
    DATABASE_URL,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE,
    DB_POOL_SIZE,
    IS_SQLITE,
)


def _engine_kwargs() -> dict:
    if IS_SQLITE:
        # Local/offline fallback only. SQLite has no network pool to manage.
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_pre_ping": True,
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_recycle": DB_POOL_RECYCLE,
        "connect_args": {"prepare_threshold": None},
    }


engine = create_engine(DATABASE_URL, future=True, **_engine_kwargs())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
