"""The ICE server list the browser needs for a peer connection.

Served from the API so rotating a TURN credential needs no Vercel rebuild.
TURN is gated because the credential is long lived and relayed traffic is
billed. Field names are WebRTC camelCase, not the API's snake_case.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import config, crud, models, schemas
from ..database import get_db
from ..deps import get_optional_user

router = APIRouter(prefix="/api", tags=["webrtc"])


def _is_known_participant(db: Session, pid: str | None, token: str | None) -> bool:
    """Whether pid and token name a real participant row.

    Not scoped to a meeting, since the token is the secret.
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
    # Omitting the nulls keeps this a clean RTCConfiguration.
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
