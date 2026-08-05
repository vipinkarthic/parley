"""WebSocket signalling server for real-time WebRTC meetings + waiting room.

Two spaces per meeting:
  • room   — admitted participants; the WebRTC mesh + presence/chat/host events.
  • lobby  — participants held in the waiting room until the host admits them.

The server only relays signalling; browsers do the media. Host status and
admission are decided server-side (from the DB via a per-participant token),
so nothing can be spoofed from the client.
"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import crud, models
from .database import SessionLocal

router = APIRouter()


SETTING_KEYS = (
    "waiting_room", "locked", "mute_on_entry", "join_before_host",
    "allow_screen_share", "allow_unmute", "allow_video", "allow_rename",
    "allow_chat", "allow_reactions",
)


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[str, dict[int, dict]] = {}
        self.lobbies: dict[str, dict[int, dict]] = {}
        self.settings: dict[str, dict] = {}

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
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            pass

    async def send_to(self, number: str, target: int, message: dict) -> None:
        peer = self.rooms.get(number, {}).get(target)
        if peer:
            await self.send(peer["ws"], message)

    async def broadcast(self, number: str, message: dict, exclude: int | None = None) -> None:
        for pid, peer in list(self.rooms.get(number, {}).items()):
            if pid != exclude:
                await self.send(peer["ws"], message)

    async def broadcast_lobby(self, number: str, message: dict) -> None:
        for p in list(self.lobbies.get(number, {}).values()):
            await self.send(p["ws"], message)

    async def notify_hosts_waiting(self, number: str) -> None:
        msg = {"type": "waiting-list", "waiting": self.waiting_list(number)}
        for hpid in self.host_pids(number):
            await self.send_to(number, hpid, msg)


hub = Hub()


def _set_admission(pid: int, meeting_id: str, admission: str) -> None:
    db = SessionLocal()
    try:
        p = db.get(models.Participant, pid)
        if p and p.meeting_id == meeting_id:
            p.admission = admission
            db.commit()
    finally:
        db.close()


def _set_waiting_room(meeting_id: str, on: bool) -> None:
    db = SessionLocal()
    try:
        m = db.get(models.Meeting, meeting_id)
        if m:
            m.waiting_room = on
            db.commit()
    finally:
        db.close()


def _update_settings(meeting_id: str, patch: dict) -> None:
    db = SessionLocal()
    try:
        m = db.get(models.Meeting, meeting_id)
        if m:
            crud.update_settings(db, m, patch)
    finally:
        db.close()


def _rename(meeting_id: str, pid: int, name: str) -> None:
    db = SessionLocal()
    try:
        p = db.get(models.Participant, pid)
        if p and p.meeting_id == meeting_id:
            p.display_name = name
            db.commit()
    finally:
        db.close()


def _deactivate(meeting_id: str, pid: int) -> None:
    db = SessionLocal()
    try:
        crud.deactivate_participant(db, meeting_id, pid)
    finally:
        db.close()


def _end_meeting(meeting_id: str) -> None:
    db = SessionLocal()
    try:
        m = db.get(models.Meeting, meeting_id)
        if m:
            crud.end_meeting(db, m)
    finally:
        db.close()


async def _admit(number: str, meeting_id: str, target: int) -> None:
    """Move a waiting participant into the room."""
    entry = hub.remove_lobby(number, target)
    if not entry:
        return
    _set_admission(target, meeting_id, "admitted")
    info = entry["info"]
    ws = entry["ws"]
    await hub.send(ws, {"type": "admitted"})
    await hub.send(ws, {"type": "peers", "peers": hub.peers(number, target)})
    hub.add_room(number, target, ws, info)
    await hub.broadcast(number, {"type": "peer-joined", "peer": info}, exclude=target)
    await hub.notify_hosts_waiting(number)


@router.websocket("/ws/meetings/{number}")
async def meeting_socket(websocket: WebSocket, number: str):
    await websocket.accept()
    params = websocket.query_params
    try:
        pid = int(params.get("pid", ""))
    except (TypeError, ValueError):
        await websocket.close(code=4001)
        return

    token = params.get("token", "")
    db = SessionLocal()
    try:
        meeting = crud.get_meeting_by_number(db, number)
        participant = (
            crud.get_participant_by_token(db, meeting.id, pid, token) if meeting else None
        )
        if meeting is None or participant is None:
            await websocket.close(code=4003)
            return
        meeting_id = meeting.id
        admission = participant.admission
        hub.settings[number] = {k: getattr(meeting, k) for k in SETTING_KEYS}
        info = {
            "id": pid,
            "displayName": participant.display_name,
            "isHost": participant.is_host,
            "muted": params.get("muted", "0") == "1",
            "videoOn": params.get("video", "1") == "1",
        }
    finally:
        db.close()

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
                for entry in hub.lobby_entries(number):
                    await _admit(number, meeting_id, entry["info"]["id"])

    try:
        while True:
            data = json.loads(await websocket.receive_text())
            mtype = data.get("type")

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
                        info["displayName"] = new_name
                        _rename(meeting_id, pid, new_name)
                        await hub.broadcast(
                            number,
                            {"type": "rename", "from": pid, "displayName": new_name},
                        )

            elif mtype == "mute-all" and info["isHost"]:
                await hub.broadcast(number, {"type": "force-mute"}, exclude=pid)
            elif mtype == "mute-peer" and info["isHost"] and "target" in data:
                await hub.send_to(number, int(data["target"]), {"type": "force-mute"})
            elif mtype == "remove-peer" and info["isHost"] and "target" in data:
                target = int(data["target"])
                await hub.send_to(number, target, {"type": "removed"})
                await hub.broadcast(number, {"type": "peer-left", "id": target}, exclude=target)
                _deactivate(meeting_id, target)
            elif mtype == "end-meeting" and info["isHost"]:
                _end_meeting(meeting_id)
                await hub.broadcast(number, {"type": "meeting-ended"})
                await hub.broadcast_lobby(number, {"type": "meeting-ended"})
            elif mtype == "admit" and info["isHost"] and "target" in data:
                await _admit(number, meeting_id, int(data["target"]))
            elif mtype == "admit-all" and info["isHost"]:
                for entry in hub.lobby_entries(number):
                    await _admit(number, meeting_id, entry["info"]["id"])
            elif mtype == "deny" and info["isHost"] and "target" in data:
                target = int(data["target"])
                entry = hub.remove_lobby(number, target)
                if entry:
                    _set_admission(target, meeting_id, "denied")
                    _deactivate(meeting_id, target)
                    await hub.send(entry["ws"], {"type": "denied"})
                    await hub.notify_hosts_waiting(number)
            elif mtype == "waiting-room" and info["isHost"]:
                on = bool(data.get("on"))
                _set_waiting_room(meeting_id, on)
                hub.settings.setdefault(number, {})["waiting_room"] = on
                await hub.broadcast(number, {"type": "waiting-room", "on": on})
                if not on:
                    for entry in hub.lobby_entries(number):
                        await _admit(number, meeting_id, entry["info"]["id"])
            elif mtype == "settings" and info["isHost"]:
                patch = {k: bool(v) for k, v in (data.get("settings") or {}).items() if k in SETTING_KEYS}
                if patch:
                    hub.settings.setdefault(number, {}).update(patch)
                    _update_settings(meeting_id, patch)
                    await hub.broadcast(number, {"type": "settings", "settings": hub.settings[number]})
                    if patch.get("waiting_room") is False:
                        for entry in hub.lobby_entries(number):
                            await _admit(number, meeting_id, entry["info"]["id"])
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
        if pid in hub.rooms.get(number, {}):
            was_host = info.get("isHost")
            hub.remove_room(number, pid)
            await hub.broadcast(number, {"type": "peer-left", "id": pid})
            if was_host and not hub.host_pids(number):
                await hub.broadcast_lobby(number, {"type": "host-present", "present": False})
        elif pid in hub.lobbies.get(number, {}):
            hub.remove_lobby(number, pid)
            await hub.notify_hosts_waiting(number)
        _deactivate(meeting_id, pid)
