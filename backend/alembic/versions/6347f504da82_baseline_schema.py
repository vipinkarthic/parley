"""baseline schema

Creates the four tables Parley has always had - users, pending_signups,
meetings, participants - as the starting point of the migration history.

Two things differ from the SQLite schema this replaces, and both are the point
of the migration rather than incidental:

* Every timestamp column is ``DateTime(timezone=True)`` (``timestamptz`` on
  Postgres). The previous schema stored naive local wall-clock time, which is
  only unambiguous for as long as the database never moves between machines.
* Three new indexes cover what the application actually filters and orders by:
  ``participants.meeting_id`` (every participant lookup), ``meetings.host_id``
  (every dashboard list) and ``meetings.start_time`` (the upcoming-meetings
  ordering).

There is no data migration. This is a baseline applied to an empty database;
the SQLite file it replaces lived on an ephemeral disk and was never durable.

Revision ID: 6347f504da82
Revises:
Create Date: 2026-09-10 03:05:40.824524
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6347f504da82"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("avatar_color", sa.String(length=9), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("pmi", sa.String(length=11), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pref_video_on_join", sa.Boolean(), nullable=False),
        sa.Column("pref_join_muted", sa.Boolean(), nullable=False),
        sa.Column("pref_mirror_video", sa.Boolean(), nullable=False),
        sa.Column("pref_hd_video", sa.Boolean(), nullable=False),
        sa.Column("pref_notifications", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "pending_signups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pending_signups_email"), "pending_signups", ["email"], unique=True
    )

    op.create_table(
        "meetings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("meeting_number", sa.String(length=11), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("passcode", sa.String(length=10), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("meeting_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("waiting_room", sa.Boolean(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("mute_on_entry", sa.Boolean(), nullable=False),
        sa.Column("join_before_host", sa.Boolean(), nullable=False),
        sa.Column("allow_screen_share", sa.Boolean(), nullable=False),
        sa.Column("allow_unmute", sa.Boolean(), nullable=False),
        sa.Column("allow_video", sa.Boolean(), nullable=False),
        sa.Column("allow_rename", sa.Boolean(), nullable=False),
        sa.Column("allow_chat", sa.Boolean(), nullable=False),
        sa.Column("allow_reactions", sa.Boolean(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_meetings_meeting_number"), "meetings", ["meeting_number"], unique=True
    )
    op.create_index(op.f("ix_meetings_host_id"), "meetings", ["host_id"], unique=False)
    op.create_index(
        op.f("ix_meetings_start_time"), "meetings", ["start_time"], unique=False
    )

    op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_host", sa.Boolean(), nullable=False),
        sa.Column("is_muted", sa.Boolean(), nullable=False),
        sa.Column("is_video_on", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("admission", sa.String(length=12), nullable=False),
        sa.Column("ws_token", sa.String(length=40), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_participants_meeting_id"), "participants", ["meeting_id"], unique=False
    )


def downgrade() -> None:
    """Drop everything, in dependency order.

    This is a real rollback path, not a formality: `alembic downgrade base`
    against an empty-ish database returns it to nothing, and the upgrade can
    then be re-applied from scratch. It destroys data, which is the correct
    behaviour for undoing the migration that created the tables.
    """
    op.drop_index(op.f("ix_participants_meeting_id"), table_name="participants")
    op.drop_table("participants")

    op.drop_index(op.f("ix_meetings_start_time"), table_name="meetings")
    op.drop_index(op.f("ix_meetings_host_id"), table_name="meetings")
    op.drop_index(op.f("ix_meetings_meeting_number"), table_name="meetings")
    op.drop_table("meetings")

    op.drop_index(op.f("ix_pending_signups_email"), table_name="pending_signups")
    op.drop_table("pending_signups")

    op.drop_table("users")
