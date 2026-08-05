"""Meeting + participant API routes."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import get_db
from ..deps import get_current_user, get_optional_user
from ..serializers import meeting_out

router = APIRouter(prefix="/api", tags=["meetings"])


@router.get("/meetings/upcoming", response_model=list[schemas.MeetingOut])
def upcoming_meetings(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return [meeting_out(db, m, user.id) for m in crud.list_upcoming(db, user.id)]


@router.get("/meetings/recent", response_model=list[schemas.MeetingOut])
def recent_meetings(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return [meeting_out(db, m, user.id) for m in crud.list_recent(db, user.id)]


@router.get("/meetings", response_model=list[schemas.MeetingOut])
def all_meetings(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return [meeting_out(db, m, user.id) for m in crud.list_all(db, user.id)]


@router.post(
    "/meetings/instant",
    response_model=schemas.MeetingOut,
    status_code=status.HTTP_201_CREATED,
)
def create_instant(
    data: schemas.InstantMeetingCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    meeting = crud.create_instant_meeting(db, data, user)
    return meeting_out(db, meeting, user.id)


@router.post("/meetings/personal", response_model=schemas.MeetingOut)
def personal_room(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """The caller's permanent personal room (PMI)."""
    meeting = crud.get_or_create_personal_meeting(db, user)
    return meeting_out(db, meeting, user.id)


@router.post(
    "/meetings/schedule",
    response_model=schemas.MeetingOut,
    status_code=status.HTTP_201_CREATED,
)
def create_scheduled(
    data: schemas.ScheduledMeetingCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    meeting = crud.create_scheduled_meeting(db, data, user)
    return meeting_out(db, meeting, user.id)


def _require_meeting(db: Session, meeting_number: str):
    meeting = crud.get_meeting_by_number(db, meeting_number)
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found. Check the meeting ID and try again.",
        )
    return meeting


@router.get("/meetings/{meeting_number}", response_model=schemas.MeetingOut)
def get_meeting(
    meeting_number: str,
    db: Session = Depends(get_db),
    viewer: models.User | None = Depends(get_optional_user),
):
    """Validate a meeting exists (used by the Join flow)."""
    meeting = _require_meeting(db, meeting_number)
    return meeting_out(db, meeting, viewer.id if viewer else None)


def _require_host(meeting: models.Meeting, user: models.User):
    if meeting.host_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the host can do that.",
        )


@router.patch("/meetings/{meeting_number}", response_model=schemas.MeetingOut)
def update_meeting(
    meeting_number: str,
    data: schemas.ScheduledMeetingUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    meeting = _require_meeting(db, meeting_number)
    _require_host(meeting, user)
    updated = crud.update_scheduled_meeting(db, meeting, data)
    return meeting_out(db, updated, user.id)


@router.delete(
    "/meetings/{meeting_number}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_meeting(
    meeting_number: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    meeting = _require_meeting(db, meeting_number)
    _require_host(meeting, user)
    crud.delete_meeting(db, meeting)
    return None


@router.post("/meetings/{meeting_number}/end", response_model=schemas.MeetingOut)
def end_meeting(
    meeting_number: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    meeting = _require_meeting(db, meeting_number)
    _require_host(meeting, user)
    return meeting_out(db, crud.end_meeting(db, meeting), user.id)


@router.patch("/meetings/{meeting_number}/settings", response_model=schemas.MeetingOut)
def update_meeting_settings(
    meeting_number: str,
    data: schemas.MeetingSettingsUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    meeting = _require_meeting(db, meeting_number)
    _require_host(meeting, user)
    updated = crud.update_settings(db, meeting, data.model_dump(exclude_none=True))
    return meeting_out(db, updated, user.id)


@router.get(
    "/meetings/{meeting_number}/participants",
    response_model=list[schemas.ParticipantOut],
)
def get_participants(meeting_number: str, db: Session = Depends(get_db)):
    meeting = _require_meeting(db, meeting_number)
    return crud.list_participants(db, meeting)


@router.post(
    "/meetings/{meeting_number}/join",
    response_model=schemas.ParticipantJoinOut,
    status_code=status.HTTP_201_CREATED,
)
def join_meeting(
    meeting_number: str,
    data: schemas.ParticipantJoin,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_optional_user),
):
    meeting = _require_meeting(db, meeting_number)
    if meeting.status == "ended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This meeting has already ended.",
        )
    is_owner = user is not None and user.id == meeting.host_id

    if not is_owner and (data.passcode or "").strip() != meeting.passcode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect meeting passcode.",
        )
    if meeting.locked and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This meeting is locked by the host.",
        )
    if (
        not is_owner
        and not meeting.join_before_host
        and meeting.meeting_type == "scheduled"
        and meeting.start_time is not None
        and datetime.now() < meeting.start_time
    ):
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail="This meeting hasn't started yet.",
        )
    if user is not None:
        other = crud.active_meeting_for_user(db, user.id, exclude_meeting_id=meeting.id)
        if other is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"You're already in another meeting (\"{other.topic}\"). "
                    "Leave it before joining or starting a new one."
                ),
            )
        crud.deactivate_user_in_meeting(db, user.id, meeting.id)
    is_host = is_owner
    if is_owner:
        admission = "admitted"
    elif meeting.waiting_room:
        admission = "waiting"
    elif crud.host_present(db, meeting) or meeting.join_before_host:
        admission = "admitted"
    else:
        admission = "waiting"
    if is_owner and meeting.status == "scheduled":
        meeting.status = "active"
        db.commit()
    participant = crud.add_participant(
        db,
        meeting,
        data.display_name,
        is_host=is_host,
        user_id=user.id if user else None,
        admission=admission,
    )
    if meeting.mute_on_entry and not is_owner:
        participant.is_muted = True
        db.commit()
    return schemas.ParticipantJoinOut(
        id=participant.id,
        display_name=participant.display_name,
        is_host=participant.is_host,
        is_muted=participant.is_muted,
        is_video_on=participant.is_video_on,
        is_active=participant.is_active,
        joined_at=participant.joined_at,
        ws_token=participant.ws_token,
        is_meeting_host=is_owner,
        admission=participant.admission,
    )


@router.post(
    "/meetings/{meeting_number}/participants/{participant_id}/mute",
    response_model=schemas.ParticipantOut,
)
def mute_participant(
    meeting_number: str,
    participant_id: int,
    muted: bool = True,
    db: Session = Depends(get_db),
):
    meeting = _require_meeting(db, meeting_number)
    participant = crud.get_participant(db, meeting, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found.")
    return crud.set_participant_muted(db, participant, muted)


@router.post("/meetings/{meeting_number}/mute-all")
def mute_all(meeting_number: str, db: Session = Depends(get_db)):
    """Host control: mute everyone except the host."""
    meeting = _require_meeting(db, meeting_number)
    muted = crud.mute_all_except_host(db, meeting)
    return {"muted": muted}


@router.delete(
    "/meetings/{meeting_number}/participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_participant(
    meeting_number: str, participant_id: int, db: Session = Depends(get_db)
):
    """Host control: remove a participant from the meeting."""
    meeting = _require_meeting(db, meeting_number)
    participant = crud.get_participant(db, meeting, participant_id)
    if participant is None:
        raise HTTPException(status_code=404, detail="Participant not found.")
    crud.remove_participant(db, participant)
    return None
