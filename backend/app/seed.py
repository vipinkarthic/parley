"""Seed the database with demo accounts (and optional sample meetings).

Idempotent: demo accounts are created only if missing, and sample meetings are
seeded once, so restarting the server never duplicates anything.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models, utils
from .config import SEED_SAMPLE_DATA
from .security import hash_password

# Ready-to-use demo logins so the app can be tested without going through the
# email OTP flow. All share the same password.
DEMO_PASSWORD = "demo1234"
DEMO_ACCOUNTS = [
    {"name": "Vipin Karthic", "email": "vipin@demo.dev", "color": "#0B5CFF"},
    {"name": "Demo1", "email": "demo1@demo.dev", "color": "#12B76A"},
    {"name": "Demo2", "email": "demo2@demo.dev", "color": "#F79009"},
]


def seed_demo_accounts(db: Session) -> None:
    """Create the demo accounts if they don't already exist (verified, so they
    can log in straight away)."""
    for acc in DEMO_ACCOUNTS:
        exists = (
            db.query(models.User).filter(models.User.email == acc["email"]).first()
        )
        if exists:
            continue
        db.add(
            models.User(
                name=acc["name"],
                email=acc["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                is_verified=True,
                avatar_color=acc["color"],
                pmi=utils.generate_meeting_number(db),
            )
        )
    db.commit()


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


def seed_database(db: Session) -> None:
    seed_demo_accounts(db)

    # Sample meetings are opt-in (SEED_SAMPLE_DATA=true), hosted by the first
    # demo account.
    if not SEED_SAMPLE_DATA:
        return

    if db.query(models.Meeting).count() > 0:
        return
    user = db.query(models.User).order_by(models.User.id.asc()).first()
    if user is None:
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
