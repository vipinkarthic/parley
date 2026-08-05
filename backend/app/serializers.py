"""Turn ORM Meeting objects into MeetingOut dicts with computed fields."""
from sqlalchemy.orm import Session

from . import crud, models, schemas, utils


def meeting_out(
    db: Session, meeting: models.Meeting, viewer_id: int | None = None
) -> schemas.MeetingOut:
    """Serialize a meeting. The passcode is only revealed to the host (the
    meeting's owner), so it isn't leaked to anyone who knows the number."""
    is_host_viewer = viewer_id is not None and viewer_id == meeting.host_id
    return schemas.MeetingOut(
        id=meeting.id,
        meeting_number=meeting.meeting_number,
        topic=meeting.topic,
        description=meeting.description,
        passcode=meeting.passcode if is_host_viewer else None,
        settings=schemas.MeetingSettings.model_validate(meeting),
        meeting_type=meeting.meeting_type,
        status=meeting.status,
        start_time=meeting.start_time,
        duration=meeting.duration,
        created_at=meeting.created_at,
        host=schemas.UserOut.model_validate(meeting.host),
        invite_link=utils.build_invite_link(meeting.meeting_number, meeting.passcode),
        participant_count=crud.active_participant_count(db, meeting),
    )
