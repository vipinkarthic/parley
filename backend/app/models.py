"""ORM models: User, Meeting, Participant.

Schema design
-------------
users          — application accounts. A single default user is seeded because
                 the assignment assumes "a default user is logged in".
meetings       — every meeting (instant or scheduled) with a unique 11-digit
                 Zoom-style meeting number, host relationship, and status.
participants   — join records for a meeting; drives the participants panel and
                 host controls (mute / remove).

Relationships
    User 1 ─── * Meeting        (host_id)
    Meeting 1 ─── * Participant  (meeting_id, cascade delete)
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    avatar_color: Mapped[str] = mapped_column(String(9), default="#0B5CFF")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

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
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_number: Mapped[str] = mapped_column(
        String(11), unique=True, index=True, nullable=False
    )
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    passcode: Mapped[str] = mapped_column(String(10), nullable=False)

    host_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    meeting_type: Mapped[str] = mapped_column(String(20), default="instant")
    status: Mapped[str] = mapped_column(String(20), default="active")

    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    host: Mapped["User"] = relationship(back_populates="meetings")
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_video_on: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # secret the client sends back on the socket - peers only see the numeric id so nobody can fake being the host
    ws_token: Mapped[str] = mapped_column(String(40), default="")

    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")
