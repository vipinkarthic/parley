"""The ICE server list the browser needs to establish a peer connection.

Served from the API rather than compiled into the frontend so that rotating a
TURN credential is an environment-variable change on Render, not a Vercel
rebuild (``NEXT_PUBLIC_*`` is inlined at build time).

Unauthenticated by design: guests join meetings without an account, and the
list ends up in the browser either way, so a gate here would cost a round trip
and protect nothing.

Field names are WebRTC's camelCase, not the API's snake_case, so the response
can be handed straight to ``new RTCPeerConnection(config)``.
"""
from fastapi import APIRouter

from .. import config, schemas

router = APIRouter(prefix="/api", tags=["webrtc"])


@router.get(
    "/ice",
    response_model=schemas.IceConfig,
    # STUN entries carry no credential; omitting the nulls keeps the payload
    # a clean RTCConfiguration rather than one with dead keys in it.
    response_model_exclude_none=True,
)
def ice_config():
    servers: list[schemas.IceServer] = []
    if config.STUN_URLS:
        servers.append(schemas.IceServer(urls=config.STUN_URLS))
    if config.TURN_URLS:
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
