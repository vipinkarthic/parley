"""The ICE server list the browser needs to establish a peer connection.

Served from the API rather than compiled into the frontend so that rotating a
TURN credential is an environment-variable change on Render, not a Vercel
rebuild (``NEXT_PUBLIC_*`` is inlined at build time).

STUN is public: it carries no credential and reveals nothing. TURN is not.
This endpoint used to hand the relay username and password to any anonymous
caller, reasoning that the value reaches the browser anyway - which is true of
a *short-lived* credential and false of the static one actually configured.
Relayed traffic is billed, so an unauthenticated endpoint that hands out a
long-lived relay credential is an open tab on someone else's account.

So TURN now requires the caller to be somebody: a signed-in user, or a
participant holding the ws_token issued to them by a successful join. Guests
have the latter and never have the former, which is why a bearer check alone
would have broken exactly the people the product is for.

Field names are WebRTC's camelCase, not the API's snake_case, so the response
can be handed straight to ``new RTCPeerConnection(config)``.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import config, crud, models, schemas
from ..database import get_db
from ..deps import get_optional_user

router = APIRouter(prefix="/api", tags=["webrtc"])


def _is_known_participant(db: Session, pid: str | None, token: str | None) -> bool:
    """Whether pid/token name a real participant row.

    Not scoped to a meeting on purpose: the token is the secret, it is a
    uuid4 hex, and the caller is asking for a relay list rather than for
    anything belonging to the meeting.
    """
    if not pid or not token:
        return False
    try:
        participant_id = int(pid)
    except (TypeError, ValueError):
        return False
    participant = (
        db.query(models.Participant)
        .filter(
            models.Participant.id == participant_id,
            models.Participant.ws_token == token,
        )
        .first()
    )
    return participant is not None and participant.admission not in (
        "denied",
        "removed",
    )


@router.get(
    "/ice",
    response_model=schemas.IceConfig,
    # STUN entries carry no credential; omitting the nulls keeps the payload
    # a clean RTCConfiguration rather than one with dead keys in it.
    response_model_exclude_none=True,
)
def ice_config(
    pid: str | None = None,
    token: str | None = None,
    db: Session = Depends(get_db),
    viewer: models.User | None = Depends(get_optional_user),
):
    servers: list[schemas.IceServer] = []
    if config.STUN_URLS:
        servers.append(schemas.IceServer(urls=config.STUN_URLS))

    entitled = viewer is not None or _is_known_participant(db, pid, token)
    if config.TURN_URLS and entitled:
        servers.append(
            schemas.IceServer(
                urls=config.TURN_URLS,
                username=config.TURN_USERNAME,
                credential=config.TURN_CREDENTIAL,
            )
        )
    return schemas.IceConfig(
        iceServers=servers,
        iceCandidatePoolSize=config.ICE_CANDIDATE_POOL_SIZE,
    )
