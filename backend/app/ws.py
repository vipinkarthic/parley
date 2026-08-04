"""WebSocket signalling server for real-time WebRTC meetings.

The browser does the actual media (WebRTC mesh); this server only relays
signalling messages between peers in the same meeting room and broadcasts
presence / state / chat / host-control events.

Message envelope is JSON. Peer-targeted messages carry a ``to`` field; the
server stamps ``from`` and forwards. Broadcasts go to everyone but the sender.
"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import crud, models
from .database import SessionLocal

router = APIRouter()


class Hub:
    """In-memory registry of connected peers per meeting room."""

    def __init__(self) -> None:
        self.rooms: dict[str, dict[int, dict]] = {}

    def add(self, number: str, pid: int, ws: WebSocket, info: dict) -> None:
        self.rooms.setdefault(number, {})[pid] = {"ws": ws, "info": info}

    def remove(self, number: str, pid: int) -> None:
        room = self.rooms.get(number)
        if room and pid in room:
            del room[pid]
            if not room:
                self.rooms.pop(number, None)

    def peers(self, number: str, exclude: int) -> list[dict]:
        room = self.rooms.get(number, {})
        return [p["info"] for pid, p in room.items() if pid != exclude]

    def info(self, number: str, pid: int) -> dict | None:
        return self.rooms.get(number, {}).get(pid, {}).get("info")

    async def send_to(self, number: str, target: int, message: dict) -> None:
        peer = self.rooms.get(number, {}).get(target)
        if peer:
            try:
                await peer["ws"].send_text(json.dumps(message))
            except Exception:
                pass

    async def broadcast(
        self, number: str, message: dict, exclude: int | None = None
    ) -> None:
        payload = json.dumps(message)
        for pid, peer in list(self.rooms.get(number, {}).items()):
            if pid == exclude:
                continue
            try:
                await peer["ws"].send_text(payload)
            except Exception:
                pass


hub = Hub()


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
            crud.get_participant_by_token(db, meeting.id, pid, token)
            if meeting
            else None
        )
        if meeting is None or participant is None:
            await websocket.close(code=4003)
            return
        meeting_id = meeting.id
        info = {
            "id": pid,
            "displayName": participant.display_name,
            "isHost": participant.is_host,
            "muted": params.get("muted", "0") == "1",
            "videoOn": params.get("video", "1") == "1",
        }
    finally:
        db.close()

    await websocket.send_text(
        json.dumps({"type": "peers", "peers": hub.peers(number, pid)})
    )
    hub.add(number, pid, websocket, info)
    await hub.broadcast(number, {"type": "peer-joined", "peer": info}, exclude=pid)

    try:
        while True:
            data = json.loads(await websocket.receive_text())
            mtype = data.get("type")

            if mtype in ("offer", "answer", "ice") and "to" in data:
                data["from"] = pid
                await hub.send_to(number, data["to"], data)

            elif mtype == "state":
                info["muted"] = bool(data.get("muted", info["muted"]))
                info["videoOn"] = bool(data.get("videoOn", info["videoOn"]))
                await hub.broadcast(
                    number,
                    {
                        "type": "state",
                        "from": pid,
                        "muted": info["muted"],
                        "videoOn": info["videoOn"],
                    },
                    exclude=pid,
                )

            elif mtype == "chat":
                await hub.broadcast(
                    number,
                    {
                        "type": "chat",
                        "from": pid,
                        "displayName": info["displayName"],
                        "text": str(data.get("text", ""))[:2000],
                    },
                    exclude=pid,
                )

            elif mtype == "reaction":
                await hub.broadcast(
                    number,
                    {"type": "reaction", "from": pid, "emoji": str(data.get("emoji", ""))[:8]},
                    exclude=pid,
                )
            elif mtype == "hand":
                info["hand"] = bool(data.get("raised"))
                await hub.broadcast(
                    number,
                    {"type": "hand", "from": pid, "raised": info["hand"]},
                    exclude=pid,
                )

            elif mtype == "share":
                await hub.broadcast(
                    number,
                    {"type": "share", "from": pid, "on": bool(data.get("on"))},
                    exclude=pid,
                )

            elif mtype == "mute-all" and info["isHost"]:
                await hub.broadcast(number, {"type": "force-mute"}, exclude=pid)
            elif mtype == "mute-peer" and info["isHost"] and "target" in data:
                await hub.send_to(number, int(data["target"]), {"type": "force-mute"})
            elif mtype == "remove-peer" and info["isHost"] and "target" in data:
                target = int(data["target"])
                await hub.send_to(number, target, {"type": "removed"})
                await hub.broadcast(
                    number, {"type": "peer-left", "id": target}, exclude=target
                )
                _deactivate(meeting_id, target)
            elif mtype == "end-meeting" and info["isHost"]:
                _end_meeting(meeting_id)
                await hub.broadcast(number, {"type": "meeting-ended"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.remove(number, pid)
        _deactivate(meeting_id, pid)
        await hub.broadcast(number, {"type": "peer-left", "id": pid})


def _deactivate(meeting_id: str, pid: int) -> None:
    db = SessionLocal()
    try:
        crud.deactivate_participant(db, meeting_id, pid)
    finally:
        db.close()


def _end_meeting(meeting_id: str) -> None:
    db = SessionLocal()
    try:
        meeting = db.get(models.Meeting, meeting_id)
        if meeting:
            crud.end_meeting(db, meeting)
    finally:
        db.close()
