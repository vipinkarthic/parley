"""Seed the database with optional sample meetings.

Idempotent: sample meetings are seeded once, so restarting the server never
duplicates anything.

Demo accounts are opt-in (SEED_DEMO_ACCOUNTS) and take their password from the
environment. They used to be seeded unconditionally on every boot, production
included, with a password committed to a public repository. Note that gating
the seeder does not delete rows an earlier boot already created; those have to
be removed from the database directly.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from . import crud, models, utils
from .config import DEMO_PASSWORD, SEED_DEMO_ACCOUNTS, SEED_SAMPLE_DATA
from .models import utcnow
from .security import hash_password

DEMO_ACCOUNTS = [
    {"name": "Demo One", "email": "demo1@parley.app", "color": "#0E7C74"},
    {"name": "Demo Two", "email": "demo2@parley.app", "color": "#12B76A"},
    {"name": "Demo Three", "email": "demo3@parley.app", "color": "#E8833A"},
]


def seed_demo_accounts(db: Session) -> None:
    """Create the demo accounts, if they do not already exist.

    Only ever called when SEED_DEMO_ACCOUNTS is on, and the password comes
    from the environment - see config.py for why both are required.
    """
    for account in DEMO_ACCOUNTS:
        exists = (
            db.query(models.User).filter(models.User.email == account["email"]).first()
        )
        if exists:
            continue
        db.add(
            models.User(
                name=account["name"],
                email=account["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                is_verified=True,
                avatar_color=account["color"],
                pmi=utils.generate_meeting_number(db),
            )
        )
    db.commit()


def seed_database(db: Session) -> None:
    if SEED_DEMO_ACCOUNTS:
        seed_demo_accounts(db)

    # Sample meetings are opt-in (SEED_SAMPLE_DATA=true), hosted by whichever
    # real account exists first. With no users there is nothing to host them,
    # and that is the ordinary state of a fresh deployment.
    if not SEED_SAMPLE_DATA:
        return

    if db.query(models.Meeting).count() > 0:
        return
    user = db.query(models.User).order_by(models.User.id.asc()).first()
    if user is None:
        return

    now = utcnow()

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
        crud.new_meeting(
            db,
            commit=False,
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
        crud.new_meeting(
            db,
            commit=False,
            host_id=user.id,
            meeting_type="scheduled",
            status="ended",
            description=None,
            **data,
        )

    db.commit()
