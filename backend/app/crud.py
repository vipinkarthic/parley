"""Database operations for meetings and participants."""
import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models, schemas, utils
from .models import utcnow


_AVATAR_COLORS = [
    "#0E7C74", "#E8833A", "#12B76A", "#7A5AF8",
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
        pmi=utils.generate_meeting_number(db),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_profile(
    db: Session, user: models.User, data: schemas.ProfileUpdate
) -> models.User:
    if data.name is not None:
        user.name = data.name.strip()
    if data.avatar_color is not None:
        user.avatar_color = data.avatar_color
    if data.avatar_url is not None:
        user.avatar_url = data.avatar_url or None
    db.commit()
    db.refresh(user)
    return user


def change_password(db: Session, user: models.User, new_hash: str) -> None:
    user.password_hash = new_hash
    db.commit()


def get_or_create_personal_meeting(
    db: Session, user: models.User
) -> models.Meeting:
    """The user's permanent personal room (meeting_number == their PMI)."""
    meeting = (
        db.query(models.Meeting)
        .filter(models.Meeting.meeting_number == user.pmi)
        .first()
    )
    if meeting is None:
        meeting = models.Meeting(
            id=uuid.uuid4().hex,
            meeting_number=user.pmi,
            passcode=utils.generate_passcode(),
            topic=f"{user.name}'s Personal Room",
            host_id=user.id,
            meeting_type="instant",
            status="active",
            start_time=utcnow(),
            duration=60,
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
    elif meeting.status == "ended":
        meeting.status = "active"
        db.commit()
        db.refresh(meeting)
    return meeting


def list_contacts(db: Session, exclude_user_id: int) -> list[dict]:
    """All other registered users, with their live presence.

    Presence is derived from whether the user currently has an active
    participant row in a meeting that has not ended.
    """
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
    busy = {row[0] for row in busy_rows}
    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "avatar_color": user.avatar_color,
            "avatar_url": user.avatar_url,
            "status": "in-meeting" if user.id in busy else "available",
        }
        for user in users
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


def _settings_kwargs(settings: "schemas.MeetingSettingsUpdate | None") -> dict:
    """Only the settings fields the creator explicitly set (others use defaults)."""
    return settings.model_dump(exclude_none=True) if settings else {}


def create_instant_meeting(
    db: Session, data: schemas.InstantMeetingCreate, host: models.User
) -> models.Meeting:
    # Reuse the host's existing instant room rather than minting a new one
    # every time they click New Meeting, which would strand the first.
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
        start_time=utcnow(),
        duration=60,
        **_settings_kwargs(data.settings),
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
        **_settings_kwargs(data.settings),
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
    admission: str = "admitted",
    join_key: str | None = None,
) -> models.Participant:
    participant = models.Participant(
        meeting_id=meeting.id,
        display_name=display_name,
        is_host=is_host,
        user_id=user_id,
        admission=admission,
        ws_token=uuid.uuid4().hex,
        join_key=join_key,
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def set_admission(
    db: Session, participant: models.Participant, admission: str
) -> models.Participant:
    participant.admission = admission
    db.commit()
    db.refresh(participant)
    return participant


def set_waiting_room(
    db: Session, meeting: models.Meeting, enabled: bool
) -> models.Meeting:
    meeting.waiting_room = enabled
    db.commit()
    db.refresh(meeting)
    return meeting


def update_settings(
    db: Session, meeting: models.Meeting, patch: dict
) -> models.Meeting:
    for key, value in patch.items():
        if key in schemas.SETTING_KEYS and value is not None:
            setattr(meeting, key, value)
    db.commit()
    db.refresh(meeting)
    return meeting


def host_present(db: Session, meeting: models.Meeting) -> bool:
    """True if the meeting's host is currently an active, admitted participant."""
    return (
        db.query(models.Participant)
        .filter(
            models.Participant.meeting_id == meeting.id,
            models.Participant.is_host == True,  # noqa: E712
            models.Participant.is_active == True,  # noqa: E712
            models.Participant.admission == "admitted",
        )
        .first()
        is not None
    )


def active_meeting_for_user(
    db: Session, user_id: int, exclude_meeting_id: str | None = None
) -> models.Meeting | None:
    """The non-ended meeting a user is currently active in, if any.

    One meeting may be excluded, which is what lets a join ask "are they
    already somewhere else?". This is what enforces one active meeting per
    account.
    """
    query = (
        db.query(models.Meeting)
        .join(models.Participant, models.Participant.meeting_id == models.Meeting.id)
        .filter(
            models.Participant.user_id == user_id,
            models.Participant.is_active == True,  # noqa: E712
            models.Meeting.status != "ended",
        )
    )
    if exclude_meeting_id:
        query = query.filter(models.Meeting.id != exclude_meeting_id)
    return query.first()


def deactivate_user_in_meeting(db: Session, user_id: int, meeting_id: str) -> None:
    """Drop any prior active sessions this user has in this meeting.

    A page refresh or a rejoin would otherwise leave the previous session
    behind as a second active row.
    """
    rows = (
        db.query(models.Participant)
        .filter(
            models.Participant.user_id == user_id,
            models.Participant.meeting_id == meeting_id,
            models.Participant.is_active == True,  # noqa: E712
        )
        .all()
    )
    for row in rows:
        row.is_active = False
    if rows:
        db.commit()


def get_participant_by_join_key(
    db: Session, meeting_id: str, join_key: str
) -> models.Participant | None:
    """The participant a previous join with this key created, if any.

    This is what makes POST /join idempotent: a retry after a lost response
    finds the row the first call committed instead of creating a second one.
    """
    return (
        db.query(models.Participant)
        .filter(
            models.Participant.meeting_id == meeting_id,
            models.Participant.join_key == join_key,
        )
        .first()
    )


def reactivate_participant(
    db: Session, participant: models.Participant
) -> models.Participant:
    """Mark a participant active again without minting a new row.

    A dropped socket deactivates the participant, and `host_present` and
    `active_participant_count` both read `is_active` - so a reconnecting
    participant that came back as an inactive row would be invisible to the
    API and, if they were the host, would leave the waiting room believing
    the host had left.
    """
    if not participant.is_active:
        participant.is_active = True
        db.commit()
        db.refresh(participant)
    return participant


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
    participant = (
        db.query(models.Participant)
        .filter(
            models.Participant.id == participant_id,
            models.Participant.meeting_id == meeting_id,
        )
        .first()
    )
    if participant and participant.is_active:
        participant.is_active = False
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
    for participant in list_participants(db, meeting):
        if not participant.is_host and not participant.is_muted:
            participant.is_muted = True
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
