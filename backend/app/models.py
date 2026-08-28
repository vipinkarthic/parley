"""ORM models: User, Meeting, Participant.

Schema design
-------------
users          - application accounts, created through signup and verified by
                 an emailed OTP before they can log in.
meetings       - every meeting (instant or scheduled) with a unique 11-digit
                 meeting number, host relationship, and status.
participants   - join records for a meeting; drives the participants panel and
                 host controls (mute / remove).

Relationships
    User 1 ─── * Meeting        (host_id)
    Meeting 1 ─── * Participant  (meeting_id, cascade delete)
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .dbtypes import UtcDateTime


def utcnow() -> datetime:
    """The application clock: timezone-aware UTC, always.

    Naive local time in a database that outlives one machine is a bug waiting
    for a deploy in a different timezone - the server runs in UTC, the person
    scheduling the meeting does not.
    """
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar_color: Mapped[str] = mapped_column(String(9), default="#0E7C74")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pmi: Mapped[str] = mapped_column(String(11), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    # Tokens carry no revocation list, so changing a password could not lock
    # out a stolen one - it stayed valid until it expired. Every token issued
    # at or before this moment is now refused, which makes "change my
    # password" mean what users already assume it means.
    password_changed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
    )

    pref_video_on_join: Mapped[bool] = mapped_column(Boolean, default=True)
    pref_join_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    pref_mirror_video: Mapped[bool] = mapped_column(Boolean, default=True)
    pref_hd_video: Mapped[bool] = mapped_column(Boolean, default=False)
    pref_notifications: Mapped[bool] = mapped_column(Boolean, default=True)

    meetings: Mapped[list["Meeting"]] = relationship(back_populates="host")


class PendingSignup(Base):
    """A signup awaiting email OTP verification.

    Holds the details entered on the signup form plus the hashed OTP. On
    successful verification the row is converted into a real ``User`` and
    deleted. One row per email (upserted on resend).
    """

    __tablename__ = "pending_signups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_number: Mapped[str] = mapped_column(
        String(11), unique=True, index=True, nullable=False
    )
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    passcode: Mapped[str] = mapped_column(String(10), nullable=False)

    # indexed: every dashboard list filters meetings by their host
    host_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    meeting_type: Mapped[str] = mapped_column(String(20), default="instant")
    status: Mapped[str] = mapped_column(String(20), default="active")
    waiting_room: Mapped[bool] = mapped_column(Boolean, default=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    mute_on_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    join_before_host: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_screen_share: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_unmute: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_video: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_rename: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_chat: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_reactions: Mapped[bool] = mapped_column(Boolean, default=True)

    # indexed: the upcoming-meetings list orders every dashboard load by this
    start_time: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True, index=True
    )
    duration: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    host: Mapped["User"] = relationship(back_populates="meetings")
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # indexed: every participant lookup filters on this, and it is the
    # busiest table in the app
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_video_on: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    admission: Mapped[str] = mapped_column(String(12), default="admitted")
    # The secret the client hands back when it opens the signalling socket.
    # Peers only ever see the numeric id, so possession of this is what
    # separates the real participant from anyone claiming to be them.
    ws_token: Mapped[str] = mapped_column(String(40), default="")
    # Idempotency key for POST /join. A join whose response is lost in flight
    # (flaky mobile network, a proxy timing out during a cold start) used to
    # create a second participant row on retry, leaving the first as a ghost
    # tile nobody could remove. Replaying the same key returns the original
    # row instead. Nullable: a client that sends no key still joins normally,
    # and NULLs do not collide under the unique constraint.
    join_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    joined_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")

    __table_args__ = (
        UniqueConstraint("meeting_id", "join_key", name="uq_participants_join_key"),
    )
