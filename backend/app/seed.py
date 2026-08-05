"""Seed the database with a default user and sample meetings.

Idempotent: only seeds when the meetings table is empty, so restarting the
server does not create duplicates.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models, utils
from .config import SEED_SAMPLE_DATA
from .demo_accounts import DEMO_ACCOUNTS, DEMO_PASSWORD
from .security import hash_password


def _make_meeting(db: Session, **kwargs) -> models.Meeting:
    m = models.Meeting(
        id=uuid.uuid4().hex,
        meeting_number=utils.generate_meeting_number(db),
        passcode=utils.generate_passcode(),
        **kwargs,
    )
    db.add(m)
    db.flush()
    return m


def seed_demo_accounts(db: Session) -> models.User:
    """Always ensure the demo accounts exist (for quick login/testing).
    Returns the first demo account."""
    first: models.User | None = None
    for acc in DEMO_ACCOUNTS:
        user = (
            db.query(models.User)
            .filter(models.User.email == acc["email"])
            .first()
        )
        if user is None:
            user = models.User(
                name=acc["name"],
                email=acc["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                is_verified=True,
                avatar_color=acc["color"],
                pmi=utils.generate_meeting_number(db),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        if first is None:
            first = user
    return first  # type: ignore[return-value]


def seed_database(db: Session) -> None:
    user = seed_demo_accounts(db)

    if not SEED_SAMPLE_DATA:
        return

    if db.query(models.Meeting).count() > 0:
        return

    now = datetime.now()

    upcoming = [
        {
            "topic": "Weekly Engineering Standup",
            "description": "Sprint progress, blockers, and planning for the week.",
            "start_time": now + timedelta(hours=3),
            "duration": 30,
        },
        {
            "topic": "Product Design Review",
            "description": "Walkthrough of the new dashboard mocks with the design team.",
            "start_time": now + timedelta(days=1, hours=2),
            "duration": 60,
        },
        {
            "topic": "1:1 with Manager",
            "description": "Career growth and quarterly goals check-in.",
            "start_time": now + timedelta(days=2, hours=5),
            "duration": 45,
        },
        {
            "topic": "Customer Onboarding Call",
            "description": "Kickoff with the new enterprise customer.",
            "start_time": now + timedelta(days=3, hours=1),
            "duration": 60,
        },
    ]
    for data in upcoming:
        _make_meeting(
            db,
            host_id=user.id,
            meeting_type="scheduled",
            status="scheduled",
            **data,
        )

    recent = [
        {
            "topic": "Backend Architecture Sync",
            "start_time": now - timedelta(days=1, hours=2),
            "duration": 45,
        },
        {
            "topic": "Marketing Campaign Retro",
            "start_time": now - timedelta(days=2),
            "duration": 30,
        },
        {
            "topic": "Interview: Frontend Engineer",
            "start_time": now - timedelta(days=3, hours=4),
            "duration": 60,
        },
    ]
    for data in recent:
        _make_meeting(
            db,
            host_id=user.id,
            meeting_type="scheduled",
            status="ended",
            description=None,
            **data,
        )

    db.commit()
