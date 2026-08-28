"""FastAPI application entrypoint for the Parley backend."""
import asyncio
import logging
import signal
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import inspect, text

from .config import APP_ENV, CORS_ORIGIN_REGEX, CORS_ORIGINS, IS_PRODUCTION
from .database import SessionLocal, engine
from .logging_setup import configure_logging, request_id_var
from .routers import auth, ice, meetings, users
from .seed import seed_database
from .ws import hub
from .ws import router as ws_router

configure_logging()

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
    logger.info(
        "Parley API ready (database: %s)",
        engine.url.render_as_string(hide_password=True),
    )
    yield
    # Catch-all for a shutdown that did not come through SIGTERM - Ctrl-C, or
    # a reload. Harmless if the handler already ran.
    await _drain_signalling()
    if installed is not None:
        signal.signal(*installed)


# The schema explorer is useful locally and is pure attack surface in
# production - it enumerates every route, parameter and model for anyone who
# asks. Off unless this is a development boot.
app = FastAPI(
    title="Parley API",
    description="Backend for Parley: meetings, auth, and the WebRTC signalling hub.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# `allow_origin_regex` was hardcoded to `https://.*\.vercel\.app`, which any
# Vercel tenant satisfies - a free, instant, attacker-controlled origin that
# the API trusted with credentials. It is env-driven now and unset by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
)

REQUEST_ID_HEADER = "X-Request-ID"

# This is an API: it serves JSON, and nothing it returns should ever be
# framed, sniffed into another content type, or leak its URL onward. The
# invite link carries a passcode, which is what makes Referrer-Policy more
# than box-ticking here.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    # A JSON API needs nothing at all, so the policy is "nothing at all".
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if IS_PRODUCTION:
        # Only in production: sending HSTS from a local http:// dev server
        # would pin localhost to https in the browser and is a nuisance to undo.
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an id, and log one line per request.

    An inbound id is honoured so a trace can be followed across a proxy;
    otherwise one is minted. It goes back out on the response, which is what
    makes an error a user reports findable in the logs.

    HTTP only: ASGI http middleware is never invoked for a websocket scope,
    so the signalling socket gets no request id and no per-request line from
    here. It logs its own failures under `parley.ws`.
    """
    incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
    request_id = incoming[:64] or uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        raise
    finally:
        request_id_var.reset(token)

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info(
        "%s %s -> %s",
        request.method,
        request.url.path,
        response.status_code,
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(users.router)
app.include_router(ice.router)
app.include_router(ws_router)


@app.get("/", tags=["health"])
def health():
    """The original health route.

    Kept as-is: Render's deployed service has its health check pointed here,
    and changing it would need a dashboard change to land at the same moment
    as the code.
    """
    return {"status": "ok", "service": "parley-api"}


@app.get("/healthz", tags=["health"])
def healthz():
    """Liveness. Deliberately does not touch the database.

    This is what the keepalive from tle-machine pings every ten minutes to
    stop Render's free tier spinning the service down. Neon's free plan meters
    compute-hours and scales its compute to zero after about five minutes
    idle, so a health check that opened a connection would hold the database
    awake around the clock - spending Neon's entire monthly allowance to keep
    Render's instance warm. Use /readyz when the database is the question.
    """
    return {"status": "ok", "service": "parley-api", "env": APP_ENV}


@app.get("/readyz", tags=["health"])
def readyz(response: Response):
    """Readiness, database included. Do not point the keepalive at this.

    The error is logged rather than returned: a driver exception can carry the
    connection string, and this endpoint is unauthenticated.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed")
        response.status_code = 503
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
