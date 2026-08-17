"""Signalling-plane benchmark: broadcast fan-out and event-loop responsiveness.

Phase 3 changes two things in the signalling hub, and each one needs a
different measurement to show anything at all:

``hub``
    ``Hub.broadcast()`` used to await each ``send`` in turn, so the cost of the
    slowest receiver was paid by everyone queued behind it. Measured against
    the ``Hub`` directly with stand-in sockets, because the effect is a
    property of the fan-out loop and injecting a known delay is the only way
    to make it reproducible. The delay is an input, not a discovery - it is
    printed with the result.

``e2e``
    The same broadcast over real websockets against a real uvicorn, all
    receivers healthy. This is the honest everyday number: on loopback with no
    slow consumer there is very little for concurrency to recover, and saying
    so is worth more than a benchmark tuned to flatter the change.

``stall``
    The second half of the phase. A handful of signalling messages used to run
    a *synchronous* database round trip inside the ``async def`` handler, which
    blocks the whole event loop - every meeting on the instance, not just the
    one that sent the message. Measured as ping/pong latency on an uninvolved
    socket while another client sends database-writing messages. Point it at a
    real remote database with --db to see the number that matters; against
    local SQLite the round trip is too cheap to show the problem.

Usage:
    python tools/bench_signalling.py hub   --peers 12 --slow 1 --slow-delay 25
    python tools/bench_signalling.py e2e   --peers 12 --iters 200
    python tools/bench_signalling.py stall --writes 40 [--db postgresql://...]

Setup happens against a throwaway SQLite file unless --db says otherwise. The
harness refuses a database whose host looks like the deployed one; see
_guard_database_url.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))


# --------------------------------------------------------------------------
# Environment. config.py reads os.environ at import time, so every one of
# these has to be set before `app` is imported anywhere.
# --------------------------------------------------------------------------

def _guard_database_url(url: str) -> str:
    """Refuse to benchmark against anything that looks like production.

    This harness writes: it creates a meeting, adds participants and renames
    them. That is harmless against a scratch database and unacceptable against
    the branch the deployed app points at. Phase 1 already lost a Neon branch's
    schema to a tool that was pointed at the wrong URL, so the check is here
    rather than in the operator's memory.
    """
    lowered = url.lower()
    for marker in ("production", "prod", "ep-mute-wave"):
        if marker in lowered:
            raise SystemExit(
                f"refusing to benchmark against a URL containing {marker!r}.\n"
                "Use a scratch database or a Neon dev branch."
            )
    return url


def configure_environment(db_url: str | None) -> str:
    os.environ.setdefault("APP_ENV", "development")
    os.environ["SEED_SAMPLE_DATA"] = "false"
    os.environ["JWT_SECRET"] = "bench-secret-not-used-anywhere-real"
    os.environ["SMTP_USER"] = ""
    os.environ["SMTP_PASS"] = ""
    if db_url:
        url = _guard_database_url(db_url)
    else:
        scratch = Path(tempfile.gettempdir()) / f"parley_bench_{uuid.uuid4().hex[:8]}.db"
        url = f"sqlite:///{scratch}"
    os.environ["DATABASE_URL"] = url
    return url


def migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def summarise(label: str, samples_ms: list[float], extra: str = "") -> dict:
    ordered = sorted(samples_ms)
    n = len(ordered)

    def pct(p: float) -> float:
        if n == 1:
            return ordered[0]
        return ordered[min(n - 1, int(round(p / 100 * (n - 1))))]

    row = {
        "label": label,
        "n": n,
        "mean": statistics.fmean(ordered),
        "p50": pct(50),
        "p95": pct(95),
        "max": ordered[-1],
    }
    print(
        f"  {label:<34} n={n:<5} "
        f"mean={row['mean']:8.2f}ms  p50={row['p50']:8.2f}ms  "
        f"p95={row['p95']:8.2f}ms  max={row['max']:8.2f}ms  {extra}"
    )
    return row


# --------------------------------------------------------------------------
# Mode: hub — Hub.broadcast() in isolation, with a known-slow receiver
# --------------------------------------------------------------------------

class StubSocket:
    """Stands in for a Starlette WebSocket inside Hub.broadcast().

    `delay` models a receiver whose send does not complete immediately - a
    peer on a slow link, or one whose transport buffer is full. It is the only
    part of this benchmark that is synthetic, and it is an input rather than a
    measurement.

    `delivered_at` is what actually shows the defect. Total broadcast time
    barely moves when a single receiver is slow, because the slow send has to
    happen either way. What changes is *when each of the other receivers gets
    the message*: awaited in turn, everyone positioned after the slow one waits
    for it; awaited concurrently, nobody does.
    """

    def __init__(self, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.received = 0
        self.delivered_at = 0.0

    async def send_text(self, _text: str) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.received += 1
        self.delivered_at = time.perf_counter()


async def run_hub(args) -> None:
    from app.ws import Hub

    number = "00000000000"
    slow_counts = sorted({int(x) for x in str(args.slow).split(",")} | {0})
    print(
        f"\nhub - Hub.broadcast() with {args.peers} receivers, "
        f"{args.iters} iterations, slow receivers delayed {args.slow_delay}ms"
    )
    print(
        "  the delay is injected, not measured; it models a receiver whose "
        "send does not return at once."
    )
    print(
        "  'fast receivers' = delivery time seen by the receivers that are NOT "
        "slow - the head-of-line cost."
    )

    for slow_count in slow_counts:
        hub = Hub()
        sockets = []
        for pid in range(1, args.peers + 1):
            # Slow receivers go first, which is the worst case for a
            # sequential loop and makes no difference to a concurrent one.
            delay = args.slow_delay / 1000 if pid <= slow_count else 0.0
            sock = StubSocket(delay)
            sockets.append(sock)
            hub.add_room(number, pid, sock, {"id": pid})

        fast = [s for s in sockets if not s.delay_s]
        message = {"type": "chat", "from": 0, "text": "x" * args.payload}
        for _ in range(5):
            await hub.broadcast(number, message)

        totals: list[float] = []
        fast_last: list[float] = []
        for _ in range(args.iters):
            started = time.perf_counter()
            await hub.broadcast(number, message)
            totals.append((time.perf_counter() - started) * 1000)
            if fast:
                fast_last.append(
                    (max(s.delivered_at for s in fast) - started) * 1000
                )

        print(f"  --- {slow_count} slow of {args.peers} ---")
        summarise("whole broadcast", totals)
        if fast_last:
            summarise("last fast receiver", fast_last)


# --------------------------------------------------------------------------
# Shared: boot a real uvicorn in a background thread
# --------------------------------------------------------------------------

class ServerHandle:
    def __init__(self, server, thread, port):
        self.server = server
        self.thread = thread
        self.port = port

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=15)


def start_server() -> ServerHandle:
    import socket

    import uvicorn

    from app.main import app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets",
        # The default loop policy is fine, but pin it so a benchmark run does
        # not silently change event loop implementation between machines.
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started:
        if time.time() > deadline:
            raise SystemExit("uvicorn did not start within 30s")
        time.sleep(0.05)
    return ServerHandle(server, thread, port)


_BENCH_ROWS: list[tuple[int, str]] = []


def cleanup() -> None:
    """Delete every row this run created. Participants cascade off the
    meeting; the host user has to go explicitly."""
    if not _BENCH_ROWS:
        return
    from app import models
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        for user_id, meeting_id in _BENCH_ROWS:
            meeting = db.get(models.Meeting, meeting_id)
            if meeting is not None:
                db.delete(meeting)
            user = db.get(models.User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()
        print(f"  cleaned up {len(_BENCH_ROWS)} scratch meeting(s)")
    except Exception as exc:
        db.rollback()
        print(f"  cleanup failed ({exc}); scratch rows may remain")
    finally:
        _BENCH_ROWS.clear()
        db.close()


def seed_room(peers: int) -> tuple[str, list[tuple[int, str]]]:
    """Create a meeting with `peers` admitted participants. Returns tokens.

    The host user id is recorded in _BENCH_ROWS so cleanup() can remove
    everything afterwards - this harness is meant to be pointed at a real
    remote database, and leaving scratch rows behind in one is rude.
    """
    from app import crud, models, schemas
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        host = models.User(
            email=f"bench-{uuid.uuid4().hex[:8]}@parley.invalid",
            name="Bench Host",
            password_hash="x",
        )
        db.add(host)
        db.commit()
        db.refresh(host)

        meeting = crud.create_instant_meeting(
            db, schemas.InstantMeetingCreate(topic="bench"), host
        )
        # A benchmark room must not gate anyone in the lobby.
        meeting.waiting_room = False
        db.commit()

        tokens = []
        for i in range(peers):
            p = crud.add_participant(
                db,
                meeting,
                display_name=f"Peer {i}",
                is_host=(i == 0),
                user_id=host.id if i == 0 else None,
                admission="admitted",
            )
            tokens.append((p.id, p.ws_token))
        _BENCH_ROWS.append((host.id, meeting.id))
        return meeting.meeting_number, tokens
    finally:
        db.close()


async def connect_peer(port: int, number: str, pid: int, token: str):
    import websockets

    url = (
        f"ws://127.0.0.1:{port}/ws/meetings/{number}"
        f"?pid={pid}&token={token}&muted=0&video=1"
    )
    ws = await websockets.connect(url, max_size=None, open_timeout=20)
    return ws


async def drain_until_quiet(ws, quiet_s: float = 0.35) -> None:
    """Swallow the join burst (peers / peer-joined) before timing anything."""
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=quiet_s)
        except asyncio.TimeoutError:
            return


# --------------------------------------------------------------------------
# Mode: e2e — real sockets, all receivers healthy
# --------------------------------------------------------------------------

async def run_e2e(args) -> None:
    handle = start_server()
    try:
        number, tokens = seed_room(args.peers)
        sockets = []
        for pid, token in tokens:
            sockets.append(await connect_peer(handle.port, number, pid, token))
            # Stagger: a simultaneous burst measures the accept path, not the
            # thing under test.
            await asyncio.sleep(0.02)

        await asyncio.gather(*(drain_until_quiet(ws) for ws in sockets))

        sender, receivers = sockets[0], sockets[1:]
        print(
            f"\ne2e — real uvicorn, {args.peers} sockets "
            f"({len(receivers)} receivers), {args.iters} broadcasts, "
            f"{args.payload}B payload"
        )

        last_ms: list[float] = []
        first_ms: list[float] = []

        for i in range(args.iters):
            payload = json.dumps(
                {"type": "chat", "text": f"{i}:" + "x" * args.payload}
            )
            started = time.perf_counter()
            await sender.send(payload)
            arrivals = await asyncio.gather(
                *(_await_chat(ws) for ws in receivers)
            )
            elapsed = [(t - started) * 1000 for t in arrivals]
            first_ms.append(min(elapsed))
            last_ms.append(max(elapsed))

        summarise("first receiver", first_ms)
        summarise("last receiver (fan-out complete)", last_ms)
    finally:
        try:
            cleanup()
        finally:
            handle.stop()


async def _await_chat(ws) -> float:
    """Wait for the next chat frame and return its arrival timestamp."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        if json.loads(raw).get("type") == "chat":
            return time.perf_counter()


# --------------------------------------------------------------------------
# Mode: stall — event-loop responsiveness while DB-writing messages run
# --------------------------------------------------------------------------

async def run_stall(args) -> None:
    handle = start_server()
    try:
        # Two peers is enough: the point is that a database write driven by
        # one socket stalls an *unrelated* socket, not that fan-out is wide.
        number, tokens = seed_room(2)
        writer = await connect_peer(handle.port, number, *tokens[0])
        prober = await connect_peer(handle.port, number, *tokens[1])
        await drain_until_quiet(writer)
        await drain_until_quiet(prober)
        # Connect does one real database round trip, and against a remote
        # database it can outlast the drain: the handler accepts the socket
        # before it loads context, so `connect_peer` returns early and the
        # load finishes in the background. Without this settle the first idle
        # probe catches the tail of it and reports a few hundred ms that has
        # nothing to do with the thing being measured. Verified: at
        # --settle 3 the outlier disappears entirely.
        await asyncio.sleep(args.settle)

        target = os.environ["DATABASE_URL"].split("@")[-1].split("/")[0]
        print(f"\nstall - event-loop blocking caused by database writes")
        print(f"  database: {target}")
        print(
            "  'rename' is the cheapest signalling message that persists: one "
            "UPDATE, no host privilege needed."
        )

        idle = await _probe(prober, args.probes)
        summarise("ping/pong, nothing else running", idle)

        # One write at a time. The ping is sent a millisecond behind the
        # rename, so it reaches the server while the handler is inside the
        # database call - which is exactly the window the phase closes.
        single = []
        for i in range(args.trials):
            await writer.send(json.dumps({"type": "rename", "name": f"Bench {i}"}))
            await asyncio.sleep(0.001)
            single.append(await _one_probe(prober))
            await asyncio.sleep(0.05)
        summarise("ping/pong behind ONE write", single)

        # And the burst, which is what a busy room actually produces.
        stop = asyncio.Event()

        async def hammer():
            for i in range(args.writes):
                if stop.is_set():
                    return
                await writer.send(
                    json.dumps({"type": "rename", "name": f"Burst {i}"})
                )
                await asyncio.sleep(0.01)

        task = asyncio.create_task(hammer())
        burst = await _probe(prober, args.probes)
        stop.set()
        await task
        summarise(f"ping/pong during {args.writes}-write burst", burst)
    finally:
        try:
            cleanup()
        finally:
            handle.stop()


async def _one_probe(ws) -> float:
    started = time.perf_counter()
    await ws.send(json.dumps({"type": "ping"}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=120)
        if json.loads(raw).get("type") == "pong":
            return (time.perf_counter() - started) * 1000


async def _probe(ws, count: int) -> list[float]:
    samples = []
    for _ in range(count):
        started = time.perf_counter()
        await ws.send(json.dumps({"type": "ping"}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            if json.loads(raw).get("type") == "pong":
                break
        samples.append((time.perf_counter() - started) * 1000)
        await asyncio.sleep(0.005)
    return samples


# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("hub", "e2e", "stall"))
    parser.add_argument("--peers", type=int, default=12)
    parser.add_argument("--iters", type=int, default=200)
    parser.add_argument("--payload", type=int, default=200,
                        help="chat text length in bytes")
    parser.add_argument("--slow", default="1",
                        help="how many receivers are delayed (hub mode); "
                             "comma-separated to sweep, e.g. 1,3,6")
    parser.add_argument("--slow-delay", type=float, default=25.0,
                        help="delay per slow receiver, ms (hub mode)")
    parser.add_argument("--writes", type=int, default=40)
    parser.add_argument("--trials", type=int, default=25,
                        help="single-write stall samples (stall mode)")
    parser.add_argument("--probes", type=int, default=60)
    parser.add_argument("--settle", type=float, default=3.0,
                        help="seconds to wait after connect before probing")
    parser.add_argument("--db", default=None,
                        help="database URL; default is a throwaway SQLite file")
    args = parser.parse_args()

    url = configure_environment(args.db)
    if args.mode in ("e2e", "stall"):
        migrate(url)

    asyncio.run(getattr(sys.modules[__name__], f"run_{args.mode}")(args))


if __name__ == "__main__":
    main()
