"""FastAPI application entrypoint for the Parley backend."""
import asyncio
import logging
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import inspect

from .config import CORS_ORIGINS
from .database import SessionLocal, engine
from .routers import auth, ice, meetings, users
from .seed import seed_database
from .ws import hub
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


async def _drain_signalling() -> None:
    """Close every signalling socket with 1012, so clients reconnect."""
    hub.shutting_down = True
    count = hub.socket_count()
    if count:
        logger.info("draining %d signalling socket(s) with 1012", count)
    await hub.close_all()


def _install_sigterm_handler() -> tuple | None:
    """Close signalling sockets deliberately when the platform stops us.

    Render sends SIGTERM on every deploy and SIGKILLs 30 seconds later. Room
    state lives in this process, so a redeploy necessarily ends every meeting
    on the instance - the only question is whether the client sees something
    it knows to retry.

    uvicorn does already close websockets with 1012 during its own graceful
    shutdown, so this is not the only thing standing between a deploy and a
    dead meeting. What doing it here adds is timing and intent: the close
    happens at once rather than on uvicorn's schedule, the hub gets to mark
    itself draining so a socket arriving mid-shutdown is turned away instead
    of admitted to a dying instance, and the teardown path can skip a
    database write per participant that a reconnect would only undo.

    The previous handler is chained, not replaced - it belongs to uvicorn and
    it is what actually makes the process exit.
    """
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGTERM)

    def handle(signum, frame):
        # A signal handler runs between bytecodes on the main thread, where
        # the only safe thing to do with a running loop is schedule onto it.
        loop.call_soon_threadsafe(lambda: loop.create_task(_drain_signalling()))
        if callable(previous):
            previous(signum, frame)

    try:
        signal.signal(signal.SIGTERM, handle)
    except ValueError:
        # Not the main thread. TestClient runs the app in a portal thread, so
        # there is no signal to install there and nothing to warn about; the
        # tests drive the drain directly instead.
        return None
    return (signal.SIGTERM, previous)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _require_schema()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    installed = _install_sigterm_handler()
    logger.info("Parley API ready (database: %s)", engine.url.render_as_string(hide_password=True))
    yield
    # Catch-all for a shutdown that did not come through SIGTERM - Ctrl-C, or
    # a reload. Harmless if the handler already ran.
    await _drain_signalling()
    if installed is not None:
        signal.signal(*installed)


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
