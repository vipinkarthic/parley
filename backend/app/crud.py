"""Database operations for meetings and participants."""
import uuid
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models, schemas, utils


_AVATAR_COLORS = [
    "#0B5CFF", "#FF7A59", "#12B76A", "#7A5AF8",
    "#F79009", "#EF4444", "#06AED4", "#EC4899",
]


def get_user_by_id(db: Session, user_id: int) -> models.User | None:
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> models.User | None:
    return (
        db.query(models.User)
        .filter(models.User.email == email.strip().lower())
        .first()
    )


def create_user(
    db: Session, name: str, email: str, password_hash: str
) -> models.User:
    color = _AVATAR_COLORS[db.query(models.User).count() % len(_AVATAR_COLORS)]
    user = models.User(
        name=name.strip(),
        email=email.strip().lower(),
        password_hash=password_hash,
        is_verified=True,
        avatar_color=color,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_contacts(db: Session, exclude_user_id: int) -> list[dict]:
    """All other registered users, with live presence derived from whether they
    currently have an active participant in a non-ended meeting."""
    users = (
        db.query(models.User)
        .filter(models.User.id != exclude_user_id)
        .order_by(models.User.name.asc())
        .all()
    )
    busy_rows = (
        db.query(models.Participant.user_id)
        .join(models.Meeting, models.Meeting.id == models.Participant.meeting_id)
        .filter(
            models.Participant.is_active == True,  # noqa: E712
            models.Participant.user_id.isnot(None),
            models.Meeting.status != "ended",
        )
        .distinct()
        .all()
    )
    busy = {r[0] for r in busy_rows}
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "avatar_color": u.avatar_color,
            "status": "in-meeting" if u.id in busy else "available",
        }
        for u in users
    ]


def update_preferences(
    db: Session, user: models.User, data: schemas.PreferencesUpdate
) -> models.User:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def upsert_pending_signup(
    db: Session,
    *,
    email: str,
    name: str,
    password_hash: str,
    code_hash: str,
    expires_at,
) -> models.PendingSignup:
    email = email.strip().lower()
    pending = (
        db.query(models.PendingSignup)
        .filter(models.PendingSignup.email == email)
        .first()
    )
    if pending is None:
        pending = models.PendingSignup(email=email)
        db.add(pending)
    pending.name = name.strip()
    pending.password_hash = password_hash
    pending.code_hash = code_hash
    pending.expires_at = expires_at
    pending.attempts = 0
    db.commit()
    db.refresh(pending)
    return pending


def get_pending_signup(db: Session, email: str) -> models.PendingSignup | None:
    return (
        db.query(models.PendingSignup)
        .filter(models.PendingSignup.email == email.strip().lower())
        .first()
    )


def delete_pending_signup(db: Session, pending: models.PendingSignup) -> None:
    db.delete(pending)
    db.commit()


def _new_meeting(db: Session, **kwargs) -> models.Meeting:
    meeting = models.Meeting(
        id=uuid.uuid4().hex,
        meeting_number=utils.generate_meeting_number(db),
        passcode=utils.generate_passcode(),
        **kwargs,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


def get_active_instant_meeting(db: Session, host_id: int) -> models.Meeting | None:
    """A host's existing, still-active instant meeting (if any)."""
    return (
        db.query(models.Meeting)
        .filter(
            models.Meeting.host_id == host_id,
            models.Meeting.meeting_type == "instant",
            models.Meeting.status == "active",
        )
        .order_by(models.Meeting.created_at.desc())
        .first()
    )


def create_instant_meeting(
    db: Session, data: schemas.InstantMeetingCreate, host: models.User
) -> models.Meeting:
    # reuse the host's existing instant room instead of spawning a new one each time they click New Meeting
    existing = get_active_instant_meeting(db, host.id)
    if existing is not None:
        return existing
    return _new_meeting(
        db,
        topic=data.topic or f"{host.name}'s Instant Meeting",
        description=data.description,
        host_id=host.id,
        meeting_type="instant",
        status="active",
        start_time=datetime.now(),
        duration=60,
    )


def create_scheduled_meeting(
    db: Session, data: schemas.ScheduledMeetingCreate, host: models.User
) -> models.Meeting:
    return _new_meeting(
        db,
        topic=data.topic,
        description=data.description,
        host_id=host.id,
        meeting_type="scheduled",
        status="scheduled",
        start_time=data.start_time,
        duration=data.duration,
    )


def get_meeting_by_number(db: Session, meeting_number: str) -> models.Meeting | None:
    """Look up by 11-digit number (spaces stripped) or by internal id."""
    cleaned = meeting_number.replace(" ", "").strip()
    return (
        db.query(models.Meeting)
        .filter(
            or_(
                models.Meeting.meeting_number == cleaned,
                models.Meeting.id == cleaned,
            )
        )
        .first()
    )


def list_upcoming(db: Session, host_id: int) -> list[models.Meeting]:
    """Host's scheduled meetings that have not ended, soonest first."""
    return (
        db.query(models.Meeting)
        .filter(
            models.Meeting.host_id == host_id,
            models.Meeting.meeting_type == "scheduled",
            models.Meeting.status != "ended",
        )
        .order_by(models.Meeting.start_time.asc())
        .all()
    )


def list_recent(db: Session, host_id: int, limit: int = 8) -> list[models.Meeting]:
    """Host's meetings that have already happened (ended), most recent first."""
    return (
        db.query(models.Meeting)
        .filter(
            models.Meeting.host_id == host_id,
            models.Meeting.status == "ended",
        )
        .order_by(models.Meeting.start_time.desc())
        .limit(limit)
        .all()
    )


def list_all(db: Session, host_id: int) -> list[models.Meeting]:
    """All of the host's meetings, newest first (for the Meetings page)."""
    return (
        db.query(models.Meeting)
        .filter(models.Meeting.host_id == host_id)
        .order_by(models.Meeting.start_time.desc().nullslast())
        .all()
    )


def end_meeting(db: Session, meeting: models.Meeting) -> models.Meeting:
    meeting.status = "ended"
    db.commit()
    db.refresh(meeting)
    return meeting


def update_scheduled_meeting(
    db: Session, meeting: models.Meeting, data: schemas.ScheduledMeetingUpdate
) -> models.Meeting:
    meeting.topic = data.topic
    meeting.description = data.description
    meeting.start_time = data.start_time
    meeting.duration = data.duration
    db.commit()
    db.refresh(meeting)
    return meeting


def delete_meeting(db: Session, meeting: models.Meeting) -> None:
    db.delete(meeting)
    db.commit()


def add_participant(
    db: Session,
    meeting: models.Meeting,
    display_name: str,
    is_host: bool = False,
    user_id: int | None = None,
) -> models.Participant:
    participant = models.Participant(
        meeting_id=meeting.id,
        display_name=display_name,
        is_host=is_host,
        user_id=user_id,
        ws_token=uuid.uuid4().hex,
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def active_meeting_for_user(
    db: Session, user_id: int, exclude_meeting_id: str | None = None
) -> models.Meeting | None:
    """The non-ended meeting a user is currently active in (excluding one), if
    any. Enforces 'one active meeting per account'."""
    q = (
        db.query(models.Meeting)
        .join(models.Participant, models.Participant.meeting_id == models.Meeting.id)
        .filter(
            models.Participant.user_id == user_id,
            models.Participant.is_active == True,  # noqa: E712
            models.Meeting.status != "ended",
        )
    )
    if exclude_meeting_id:
        q = q.filter(models.Meeting.id != exclude_meeting_id)
    return q.first()


def deactivate_user_in_meeting(db: Session, user_id: int, meeting_id: str) -> None:
    """Drop any prior active sessions this user has in this meeting (handles a
    page refresh / rejoin cleanly)."""
    rows = (
        db.query(models.Participant)
        .filter(
            models.Participant.user_id == user_id,
            models.Participant.meeting_id == meeting_id,
            models.Participant.is_active == True,  # noqa: E712
        )
        .all()
    )
    for r in rows:
        r.is_active = False
    if rows:
        db.commit()


def get_participant_by_token(
    db: Session, meeting_id: str, participant_id: int, ws_token: str
) -> models.Participant | None:
    return (
        db.query(models.Participant)
        .filter(
            models.Participant.id == participant_id,
            models.Participant.meeting_id == meeting_id,
            models.Participant.ws_token == ws_token,
        )
        .first()
    )


def deactivate_participant(db: Session, meeting_id: str, participant_id: int) -> None:
    p = (
        db.query(models.Participant)
        .filter(
            models.Participant.id == participant_id,
            models.Participant.meeting_id == meeting_id,
        )
        .first()
    )
    if p and p.is_active:
        p.is_active = False
        db.commit()


def list_participants(db: Session, meeting: models.Meeting) -> list[models.Participant]:
    return (
        db.query(models.Participant)
        .filter(
            models.Participant.meeting_id == meeting.id,
            models.Participant.is_active == True,  # noqa: E712
        )
        .order_by(models.Participant.joined_at.asc())
        .all()
    )


def get_participant(
    db: Session, meeting: models.Meeting, participant_id: int
) -> models.Participant | None:
    return (
        db.query(models.Participant)
        .filter(
            models.Participant.id == participant_id,
            models.Participant.meeting_id == meeting.id,
        )
        .first()
    )


def set_participant_muted(
    db: Session, participant: models.Participant, muted: bool
) -> models.Participant:
    participant.is_muted = muted
    db.commit()
    db.refresh(participant)
    return participant


def mute_all_except_host(db: Session, meeting: models.Meeting) -> int:
    count = 0
    for p in list_participants(db, meeting):
        if not p.is_host and not p.is_muted:
            p.is_muted = True
            count += 1
    db.commit()
    return count


def remove_participant(db: Session, participant: models.Participant) -> None:
    participant.is_active = False
    db.commit()


def active_participant_count(db: Session, meeting: models.Meeting) -> int:
    return (
        db.query(models.Participant)
        .filter(
            models.Participant.meeting_id == meeting.id,
            models.Participant.is_active == True,  # noqa: E712
        )
        .count()
    )
