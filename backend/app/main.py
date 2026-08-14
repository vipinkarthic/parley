"""FastAPI application entrypoint for the Parley backend."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import inspect

from .config import CORS_ORIGINS
from .database import SessionLocal, engine
from .routers import auth, ice, meetings, users
from .seed import seed_database
from .ws import router as ws_router

logger = logging.getLogger("parley")


def _require_schema() -> None:
    """Fail fast, and legibly, if migrations have not been run.

    Alembic owns the schema now; `Base.metadata.create_all()` used to run here
    and was removed deliberately. Creating tables on boot papers over a failed
    migration and lets the live schema drift away from the migration history,
    which is precisely the thing that makes a database hard to trust.
    """
    tables = set(inspect(engine).get_table_names())
    missing = {"users", "pending_signups", "meetings", "participants"} - tables
    if missing:
        raise RuntimeError(
            f"Database schema is missing {sorted(missing)}. Run migrations "
            "first:  alembic upgrade head"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _require_schema()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    logger.info("Parley API ready (database: %s)", engine.url.render_as_string(hide_password=True))
    yield


app = FastAPI(
    title="Parley API",
    description="Backend for Parley: meetings, auth, and the WebRTC signalling hub.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(users.router)
app.include_router(ice.router)
app.include_router(ws_router)


@app.get("/", tags=["health"])
def health():
    return {"status": "ok", "service": "parley-api"}
