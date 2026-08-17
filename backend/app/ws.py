"""WebSocket signalling server for real-time WebRTC meetings + waiting room.

Two spaces per meeting:
  • room   - admitted participants; the WebRTC mesh + presence/chat/host events.
  • lobby  - participants held in the waiting room until the host admits them.

The server only relays signalling; browsers do the media. Host status and
admission are decided server-side (from the DB via a per-participant token),
so nothing can be spoofed from the client.
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from . import crud, models
from .database import SessionLocal

router = APIRouter()

# Application close codes. The 4000-4999 range is reserved for the application
# by the WebSocket spec. The client's reconnect logic keys off these: 4001,
# 4003, 4004 and 4005 are final for the meeting and must not be retried, while
# 4009 means "this socket was replaced" and the newer socket carries on.
WS_BAD_PID = 4001
WS_UNAUTHORISED = 4003
WS_DENIED = 4004
WS_MEETING_ENDED = 4005
WS_SUPERSEDED = 4009

# RFC 6455's own "Service Restart". A redeploy is the ordinary case for a free
# Render service, and it is not an error - the client is expected to come back.
WS_SERVICE_RESTART = 1012


SETTING_KEYS = (
    "waiting_room", "locked", "mute_on_entry", "join_before_host",
    "allow_screen_share", "allow_unmute", "allow_video", "allow_rename",
    "allow_chat", "allow_reactions",
)


async def _fan_out(coros) -> None:
    """Await many independent sends together.

    `return_exceptions=True` because these coroutines are already
    individually guarded; the flag is there so that a cancellation or a
    surprise from one socket cannot leave the rest un-awaited, which would
    surface later as "coroutine was never awaited".
    """
    await asyncio.gather(*coros, return_exceptions=True)


async def _close_quietly(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:
        pass


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[str, dict[int, dict]] = {}
        self.lobbies: dict[str, dict[int, dict]] = {}
        self.settings: dict[str, dict] = {}
        # Set on SIGTERM. Room state lives in this process, so a redeploy
        # necessarily ends every meeting on this instance; the flag is what
        # turns that into a reconnect rather than a failure.
        self.shutting_down = False

    def socket_count(self) -> int:
        return sum(len(r) for r in self.rooms.values()) + sum(
            len(lobby) for lobby in self.lobbies.values()
        )

    async def close_all(self, code: int = WS_SERVICE_RESTART) -> None:
        """Close every socket with a code the client treats as retryable.

        Materialises the list first: closing a socket runs its handler's
        teardown, which mutates the dicts being walked.

        Closed concurrently for the same reason broadcasts are. Render SIGKILLs
        thirty seconds after SIGTERM, and one unresponsive socket must not eat
        that budget on behalf of everyone still waiting to be told to reconnect.
        """
        entries = [
            entry
            for group in (self.rooms, self.lobbies)
            for space in list(group.values())
            for entry in list(space.values())
        ]
        await _fan_out(_close_quietly(entry["ws"], code) for entry in entries)
        self.rooms.clear()
        self.lobbies.clear()

    def setting(self, number: str, key: str) -> bool:
        return self.settings.get(number, {}).get(key, True)

    def add_room(self, number: str, pid: int, ws: WebSocket, info: dict) -> None:
        self.rooms.setdefault(number, {})[pid] = {"ws": ws, "info": info}

    def remove_room(self, number: str, pid: int) -> None:
        room = self.rooms.get(number)
        if room and pid in room:
            del room[pid]
            if not room:
                self.rooms.pop(number, None)

    def entry(self, number: str, pid: int) -> dict | None:
        """This participant's live socket entry, in the room or the lobby."""
        return (
            self.rooms.get(number, {}).get(pid)
            or self.lobbies.get(number, {}).get(pid)
        )

    def owns(self, number: str, pid: int, ws: WebSocket) -> bool:
        """Whether `ws` is still the socket registered for this participant.

        Both dicts are keyed by participant id, so a reconnect that arrives
        before the old socket's close is processed replaces the entry. Without
        this check the displaced socket's teardown would announce peer-left and
        deactivate the row out from under the connection that is actually live.
        """
        entry = self.entry(number, pid)
        return entry is not None and entry["ws"] is ws

    def peers(self, number: str, exclude: int) -> list[dict]:
        return [p["info"] for pid, p in self.rooms.get(number, {}).items() if pid != exclude]

    def host_pids(self, number: str) -> list[int]:
        return [pid for pid, p in self.rooms.get(number, {}).items() if p["info"].get("isHost")]

    def add_lobby(self, number: str, pid: int, ws: WebSocket, info: dict) -> None:
        self.lobbies.setdefault(number, {})[pid] = {"ws": ws, "info": info}

    def remove_lobby(self, number: str, pid: int) -> dict | None:
        lobby = self.lobbies.get(number)
        entry = None
        if lobby and pid in lobby:
            entry = lobby.pop(pid)
            if not lobby:
                self.lobbies.pop(number, None)
        return entry

    def waiting_list(self, number: str) -> list[dict]:
        return [
            {"id": p["info"]["id"], "displayName": p["info"]["displayName"]}
            for p in self.lobbies.get(number, {}).values()
        ]

    def lobby_entries(self, number: str) -> list[dict]:
        return list(self.lobbies.get(number, {}).values())

    async def send(self, ws: WebSocket, message: dict) -> None:
        await self._send_text(ws, json.dumps(message))

    @staticmethod
    async def _send_text(ws: WebSocket, text: str) -> None:
        """A send that cannot fail the caller.

        A socket that has gone away must not abort a fan-out that is still
        delivering to everyone else - and its handler's own teardown is what
        removes it from the room, not this.
        """
        try:
            await ws.send_text(text)
        except Exception:
            pass

    async def send_to(self, number: str, target: int, message: dict) -> None:
        peer = self.rooms.get(number, {}).get(target)
        if peer:
            await self.send(peer["ws"], message)

    async def broadcast(self, number: str, message: dict, exclude: int | None = None) -> None:
        """Fan a message out to the room, concurrently.

        Awaiting each send in turn makes the slowest receiver everyone else's
        problem: a peer whose transport buffer is full holds up every peer
        positioned after it in the dict, for as long as its own send takes.
        The room is small, so the cost of the sequential version is not the
        total work - it is the head-of-line blocking, and it lands on the
        participants who did nothing wrong.

        The payload is serialised once here rather than once per recipient.
        """
        peers = [
            peer["ws"]
            for pid, peer in self.rooms.get(number, {}).items()
            if pid != exclude
        ]
        await self._send_many(peers, message)

    async def broadcast_lobby(self, number: str, message: dict) -> None:
        sockets = [p["ws"] for p in self.lobbies.get(number, {}).values()]
        await self._send_many(sockets, message)

    async def notify_hosts_waiting(self, number: str) -> None:
        msg = {"type": "waiting-list", "waiting": self.waiting_list(number)}
        room = self.rooms.get(number, {})
        hosts = [
            room[hpid]["ws"] for hpid in self.host_pids(number) if hpid in room
        ]
        await self._send_many(hosts, msg)

    async def _send_many(self, sockets: list, message: dict) -> None:
        """Send one already-known message to many sockets at once."""
        if not sockets:
            return
        text = json.dumps(message)
        if len(sockets) == 1:
            await self._send_text(sockets[0], text)
            return
        await _fan_out(self._send_text(ws, text) for ws in sockets)


hub = Hub()


# ---------------------------------------------------------------------------
# Database access from the signalling handler.
#
# Every function below is synchronous SQLAlchemy, and the handler that calls
# them is `async def`. Called directly, each one blocks the event loop for the
# whole round trip - which means it blocks *every* meeting on the instance,
# not just the socket that triggered it. That is cheap to miss on SQLite,
# where a write is microseconds. It is not cheap in production: Render runs in
# Oregon and Neon in Singapore, so a single persisted `rename` was measured
# stalling an uninvolved participant's ping/pong for ~450ms.
#
# So each one is a plain sync `_do_*` that a thin `await`-able wrapper hands
# to the threadpool - the same pool FastAPI already runs its sync endpoints
# in. The session stays short-lived and thread-confined: a Session held open
# across an await and shared between threads is neither thread-safe nor
# affordable, since it would hold one pooled connection for the life of the
# socket and the pool is ten connections wide.
#
# Note the ordering rule the callers follow: live state lives in the hub, and
# the database is for what has to survive a reconnect. Presentation changes
# (rename, settings) are broadcast first and persisted after, so no
# participant waits on a cross-Pacific write to see them. Authorisation
# changes (admission, ended) are persisted first, because a reconnect re-reads
# them and must not be able to undo the decision.
# ---------------------------------------------------------------------------


def _do_set_admission(pids: list[int], meeting_id: str, admission: str) -> None:
    """Set admission for one or many participants in a single transaction.

    `admit-all` and the auto-admit that runs when a host arrives with the
    waiting room off both walk the whole lobby. One session per guest meant
    one full round trip per guest, serially, with the event loop blocked for
    all of them.
    """
    if not pids:
        return
    db = SessionLocal()
    try:
        rows = (
            db.query(models.Participant)
            .filter(
                models.Participant.id.in_(pids),
                models.Participant.meeting_id == meeting_id,
            )
            .all()
        )
        for p in rows:
            p.admission = admission
        if rows:
            db.commit()
    finally:
        db.close()


async def _set_admission(pids: list[int], meeting_id: str, admission: str) -> None:
    await run_in_threadpool(_do_set_admission, pids, meeting_id, admission)


def _do_set_waiting_room(meeting_id: str, on: bool) -> None:
    db = SessionLocal()
    try:
        m = db.get(models.Meeting, meeting_id)
        if m:
            m.waiting_room = on
            db.commit()
    finally:
        db.close()


async def _set_waiting_room(meeting_id: str, on: bool) -> None:
    await run_in_threadpool(_do_set_waiting_room, meeting_id, on)


def _do_update_settings(meeting_id: str, patch: dict) -> None:
    db = SessionLocal()
    try:
        m = db.get(models.Meeting, meeting_id)
        if m:
            crud.update_settings(db, m, patch)
    finally:
        db.close()


async def _update_settings(meeting_id: str, patch: dict) -> None:
    await run_in_threadpool(_do_update_settings, meeting_id, patch)


def _do_rename(meeting_id: str, pid: int, name: str) -> None:
    db = SessionLocal()
    try:
        p = db.get(models.Participant, pid)
        if p and p.meeting_id == meeting_id:
            p.display_name = name
            db.commit()
    finally:
        db.close()


async def _rename(meeting_id: str, pid: int, name: str) -> None:
    await run_in_threadpool(_do_rename, meeting_id, pid, name)


def _do_deactivate(meeting_id: str, pid: int) -> None:
    db = SessionLocal()
    try:
        crud.deactivate_participant(db, meeting_id, pid)
    finally:
        db.close()


async def _deactivate(meeting_id: str, pid: int) -> None:
    await run_in_threadpool(_do_deactivate, meeting_id, pid)


def _do_deny(meeting_id: str, pid: int) -> None:
    """Mark a guest denied and inactive in one transaction.

    Two separate sessions for two single-column updates on the same row is two
    round trips for no reason, and it left a window where a participant was
    denied but still counted as active.
    """
    db = SessionLocal()
    try:
        p = db.get(models.Participant, pid)
        if p and p.meeting_id == meeting_id:
            p.admission = "denied"
            p.is_active = False
            db.commit()
    finally:
        db.close()


async def _deny(meeting_id: str, pid: int) -> None:
    await run_in_threadpool(_do_deny, meeting_id, pid)


def _do_end_meeting(meeting_id: str) -> None:
    db = SessionLocal()
    try:
        m = db.get(models.Meeting, meeting_id)
        if m:
            crud.end_meeting(db, m)
    finally:
        db.close()


async def _end_meeting(meeting_id: str) -> None:
    await run_in_threadpool(_do_end_meeting, meeting_id)


def _do_load_context(number: str, pid: int, token: str) -> dict:
    """Everything the socket needs from the database, in one session.

    This is the only read the connection performs. Authentication, the
    terminal-state checks, the meeting settings snapshot, the participant's
    display name and host flag, and the reactivation that undoes the previous
    socket's teardown all used to be spread over two sessions and two round
    trips; they are one transaction now, and nothing after this point touches
    the database until the participant does something that has to be
    persisted.

    Returns either ``{"close": <code>}`` or the context. Raising for the
    rejection cases would mean building exception types whose only job is to
    carry an integer across a threadpool boundary.
    """
    db = SessionLocal()
    try:
        meeting = crud.get_meeting_by_number(db, number)
        participant = (
            crud.get_participant_by_token(db, meeting.id, pid, token)
            if meeting
            else None
        )
        if meeting is None or participant is None:
            return {"close": WS_UNAUTHORISED}
        # Terminal states get their own codes so the client stops retrying.
        # This matters now that the client reconnects on its own: a denied
        # guest still holds a valid ws_token, and `admission == "denied"` is
        # not "waiting", so a reconnect would otherwise have walked them
        # straight into the room the host just refused them.
        if participant.admission == "denied":
            return {"close": WS_DENIED}
        if meeting.status == "ended":
            return {"close": WS_MEETING_ENDED}

        # A reconnect reuses the participant row, so the flag the dropped
        # socket cleared has to be put back before anyone reads presence off
        # it. Same session as the load - it is the same row.
        crud.reactivate_participant(db, participant)

        return {
            "meeting_id": meeting.id,
            "admission": participant.admission,
            "settings": {k: getattr(meeting, k) for k in SETTING_KEYS},
            "display_name": participant.display_name,
            "is_host": participant.is_host,
        }
    finally:
        db.close()


async def _load_context(number: str, pid: int, token: str) -> dict:
    return await run_in_threadpool(_do_load_context, number, pid, token)


async def _evict_existing_socket(number: str, pid: int, keep: WebSocket) -> None:
    """Make room for a reconnecting participant by closing their old socket.

    One participant, one socket. A reconnect regularly arrives before the old
    socket's close has been processed - a laptop waking, a redeploy - and both
    hub dicts are keyed by participant id, so the newcomer would silently
    displace the old entry and leave a zombie handler behind. Evicting it here,
    deliberately and with a distinct code, is what makes the displacement
    visible instead of a race.
    """
    stale = hub.entry(number, pid)
    if stale is None or stale["ws"] is keep:
        return
    hub.remove_room(number, pid)
    hub.remove_lobby(number, pid)
    await _close_quietly(stale["ws"], WS_SUPERSEDED)


async def _admit(number: str, meeting_id: str, *targets: int) -> None:
    """Move waiting participants into the room.

    Variadic on purpose. `admit-all`, and the auto-admit that runs when a host
    joins a room whose waiting room is off, both used to call this once per
    guest - and each call opened its own session, so a lobby of six guests was
    six serial round trips with the event loop blocked throughout. The
    admission write is now one transaction for the whole batch, and the
    resulting fan-out is one broadcast per admitted guest rather than one per
    guest per guest.
    """
    entries = []
    for target in targets:
        entry = hub.remove_lobby(number, target)
        if entry:
            entries.append(entry)
    if not entries:
        return

    # Persisted before anyone is told, because admission is re-read on
    # reconnect: a guest who saw "admitted" and then reconnected into the
    # lobby because the write had not landed is a worse bug than a slow admit.
    await _set_admission(
        [e["info"]["id"] for e in entries], meeting_id, "admitted"
    )

    for entry in entries:
        info = entry["info"]
        ws = entry["ws"]
        target = info["id"]
        await hub.send(ws, {"type": "admitted"})
        await hub.send(ws, {"type": "peers", "peers": hub.peers(number, target)})
        hub.add_room(number, target, ws, info)
        await hub.broadcast(
            number, {"type": "peer-joined", "peer": info}, exclude=target
        )
    await hub.notify_hosts_waiting(number)


def _lobby_pids(number: str) -> list[int]:
    return [e["info"]["id"] for e in hub.lobby_entries(number)]


@router.websocket("/ws/meetings/{number}")
async def meeting_socket(websocket: WebSocket, number: str):
    await websocket.accept()
    if hub.shutting_down:
        # Admitting anyone now would hand them room state that is about to
        # disappear with the process. Turn them away retryably instead, so
        # they land on the instance that replaces this one.
        await websocket.close(code=WS_SERVICE_RESTART)
        return
    params = websocket.query_params
    try:
        pid = int(params.get("pid", ""))
    except (TypeError, ValueError):
        await websocket.close(code=WS_BAD_PID)
        return

    token = params.get("token", "")
    # The one and only database round trip this connection makes up front:
    # authentication, terminal-state checks, the settings snapshot and the
    # reconnect reactivation, in a single session, off the event loop.
    context = await _load_context(number, pid, token)
    if "close" in context:
        await websocket.close(code=context["close"])
        return

    meeting_id = context["meeting_id"]
    admission = context["admission"]
    hub.settings[number] = context["settings"]
    info = {
        "id": pid,
        "displayName": context["display_name"],
        "isHost": context["is_host"],
        "muted": params.get("muted", "0") == "1",
        "videoOn": params.get("video", "1") == "1",
    }

    await _evict_existing_socket(number, pid, websocket)

    waiting = admission == "waiting"

    if waiting:
        hub.add_lobby(number, pid, websocket, info)
        await hub.send(
            websocket,
            {"type": "waiting", "hostPresent": len(hub.host_pids(number)) > 0},
        )
        await hub.notify_hosts_waiting(number)
    else:
        await hub.send(websocket, {"type": "peers", "peers": hub.peers(number, pid)})
        hub.add_room(number, pid, websocket, info)
        await hub.broadcast(number, {"type": "peer-joined", "peer": info}, exclude=pid)
        if info["isHost"]:
            await hub.send(
                websocket, {"type": "waiting-list", "waiting": hub.waiting_list(number)}
            )
            await hub.broadcast_lobby(number, {"type": "host-present", "present": True})
            if not hub.setting(number, "waiting_room"):
                await _admit(number, meeting_id, *_lobby_pids(number))

    try:
        while True:
            data = json.loads(await websocket.receive_text())
            mtype = data.get("type")

            # Heartbeat, answered before the lobby gate because someone
            # waiting to be admitted needs their socket checked too. A laptop
            # that slept leaves a half-open TCP connection that never fires a
            # close event, so the client's own unanswered pings are the only
            # thing that notices.
            if mtype == "ping":
                await hub.send(websocket, {"type": "pong"})
                continue

            # ignore anything from people still in the lobby - checked live so a just-admitted guest relays right away
            if pid not in hub.rooms.get(number, {}):
                continue

            if mtype in ("offer", "answer", "ice") and "to" in data:
                data["from"] = pid
                await hub.send_to(number, data["to"], data)
            elif mtype == "state":
                new_muted = bool(data.get("muted", info["muted"]))
                if (
                    not info["isHost"]
                    and not new_muted
                    and not hub.setting(number, "allow_unmute")
                ):
                    await hub.send(websocket, {"type": "force-mute"})
                    continue
                info["muted"] = new_muted
                info["videoOn"] = bool(data.get("videoOn", info["videoOn"]))
                await hub.broadcast(
                    number,
                    {"type": "state", "from": pid, "muted": info["muted"], "videoOn": info["videoOn"]},
                    exclude=pid,
                )
            elif mtype == "chat":
                if not info["isHost"] and not hub.setting(number, "allow_chat"):
                    continue
                await hub.broadcast(
                    number,
                    {"type": "chat", "from": pid, "displayName": info["displayName"], "text": str(data.get("text", ""))[:2000]},
                    exclude=pid,
                )
            elif mtype == "reaction":
                if not info["isHost"] and not hub.setting(number, "allow_reactions"):
                    continue
                await hub.broadcast(
                    number,
                    {"type": "reaction", "from": pid, "emoji": str(data.get("emoji", ""))[:8]},
                    exclude=pid,
                )
            elif mtype == "hand":
                info["hand"] = bool(data.get("raised"))
                await hub.broadcast(
                    number, {"type": "hand", "from": pid, "raised": info["hand"]}, exclude=pid
                )
            elif mtype == "share":
                if not info["isHost"] and not hub.setting(number, "allow_screen_share"):
                    await hub.send(websocket, {"type": "share-denied"})
                    continue
                on = bool(data.get("on"))
                # stash it on the peer so late joiners know about the screen share
                info["sharing"] = on
                info["screenSid"] = data.get("streamId") if on else None
                await hub.broadcast(
                    number,
                    {"type": "share", "from": pid, "on": on, "streamId": info["screenSid"]},
                    exclude=pid,
                )
            elif mtype == "rename":
                if info["isHost"] or hub.setting(number, "allow_rename"):
                    new_name = str(data.get("name", "")).strip()[:120]
                    if new_name:
                        # Announced before it is stored. The hub is what the
                        # room reads its live state from; the row only has to
                        # be right by the time somebody reconnects. Persisting
                        # first would make every rename cost a round trip to
                        # Singapore before anyone saw it.
                        info["displayName"] = new_name
                        await hub.broadcast(
                            number,
                            {"type": "rename", "from": pid, "displayName": new_name},
                        )
                        await _rename(meeting_id, pid, new_name)

            elif mtype == "mute-all" and info["isHost"]:
                await hub.broadcast(number, {"type": "force-mute"}, exclude=pid)
            elif mtype == "mute-peer" and info["isHost"] and "target" in data:
                await hub.send_to(number, int(data["target"]), {"type": "force-mute"})
            elif mtype == "remove-peer" and info["isHost"] and "target" in data:
                target = int(data["target"])
                await hub.send_to(number, target, {"type": "removed"})
                await hub.broadcast(number, {"type": "peer-left", "id": target}, exclude=target)
                await _deactivate(meeting_id, target)
            elif mtype == "end-meeting" and info["isHost"]:
                # Persisted first: `status == "ended"` is what stops a
                # reconnect walking back into a meeting the host closed.
                await _end_meeting(meeting_id)
                await hub.broadcast(number, {"type": "meeting-ended"})
                await hub.broadcast_lobby(number, {"type": "meeting-ended"})
            elif mtype == "admit" and info["isHost"] and "target" in data:
                await _admit(number, meeting_id, int(data["target"]))
            elif mtype == "admit-all" and info["isHost"]:
                await _admit(number, meeting_id, *_lobby_pids(number))
            elif mtype == "deny" and info["isHost"] and "target" in data:
                target = int(data["target"])
                entry = hub.remove_lobby(number, target)
                if entry:
                    # One transaction for both columns; a denied guest who is
                    # still flagged active is counted as present by the API.
                    await _deny(meeting_id, target)
                    await hub.send(entry["ws"], {"type": "denied"})
                    await hub.notify_hosts_waiting(number)
            elif mtype == "waiting-room" and info["isHost"]:
                on = bool(data.get("on"))
                hub.settings.setdefault(number, {})["waiting_room"] = on
                await hub.broadcast(number, {"type": "waiting-room", "on": on})
                if not on:
                    await _admit(number, meeting_id, *_lobby_pids(number))
                await _set_waiting_room(meeting_id, on)
            elif mtype == "settings" and info["isHost"]:
                patch = {k: bool(v) for k, v in (data.get("settings") or {}).items() if k in SETTING_KEYS}
                if patch:
                    hub.settings.setdefault(number, {}).update(patch)
                    await hub.broadcast(number, {"type": "settings", "settings": hub.settings[number]})
                    if patch.get("waiting_room") is False:
                        await _admit(number, meeting_id, *_lobby_pids(number))
                    await _update_settings(meeting_id, patch)
            elif mtype == "spotlight" and info["isHost"]:
                await hub.broadcast(
                    number, {"type": "spotlight", "target": data.get("target")}
                )
            elif mtype == "lower-hand" and info["isHost"] and "target" in data:
                target = int(data["target"])
                await hub.send_to(number, target, {"type": "lower-hand"})
                await hub.broadcast(
                    number, {"type": "hand", "from": target, "raised": False}
                )
            elif mtype == "ask-unmute" and info["isHost"] and "target" in data:
                await hub.send_to(number, int(data["target"]), {"type": "ask-unmute"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # Only tear down if this socket still owns the participant slot. If a
        # reconnect displaced us, the live socket is already registered under
        # this id - announcing peer-left or deactivating the row here would
        # knock out the connection that replaced us.
        if hub.owns(number, pid, websocket):
            if pid in hub.rooms.get(number, {}):
                was_host = info.get("isHost")
                hub.remove_room(number, pid)
                await hub.broadcast(number, {"type": "peer-left", "id": pid})
                if was_host and not hub.host_pids(number):
                    await hub.broadcast_lobby(
                        number, {"type": "host-present", "present": False}
                    )
            elif pid in hub.lobbies.get(number, {}):
                hub.remove_lobby(number, pid)
                await hub.notify_hosts_waiting(number)
            # During a redeploy every participant is about to reconnect, so
            # marking them inactive would make the API report empty meetings
            # and hostless waiting rooms for the length of the deploy - and
            # spend one database write per participant to do it.
            if not hub.shutting_down:
                await _deactivate(meeting_id, pid)
