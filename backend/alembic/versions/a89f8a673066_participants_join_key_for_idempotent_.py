"""participants.join_key for idempotent joins

POST /join was not idempotent. A join whose response never reached the browser
- a flaky mobile network, or a proxy giving up during one of Render's 30-60s
cold starts - left a committed participant row the client knew nothing about.
Retrying created a second one, and the first became a tile nobody was behind
and the host could not remove.

The client now sends an ``Idempotency-Key``; replaying it returns the original
row rather than creating another. Nullable, because a client that sends no key
still joins normally, and NULLs do not collide under a unique constraint on
either SQLite or Postgres.

Scoped to ``(meeting_id, join_key)`` rather than globally unique: keys are
generated per browser and a collision across two unrelated meetings should not
be an error.

Revision ID: a89f8a673066
Revises: 6347f504da82
Create Date: 2026-09-10 05:46:50.144491
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a89f8a673066"
down_revision: Union[str, None] = "6347f504da82"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch mode is what makes this work on SQLite, which cannot ALTER a table
    # to add a constraint; on Postgres it emits plain ALTER TABLE statements.
    with op.batch_alter_table("participants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("join_key", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_participants_join_key", ["meeting_id", "join_key"]
        )


def downgrade() -> None:
    """Drops the key. Joins go back to being non-idempotent, but nothing else
    depends on the column, so this is a clean rollback rather than a data loss."""
    with op.batch_alter_table("participants", schema=None) as batch_op:
        batch_op.drop_constraint("uq_participants_join_key", type_="unique")
        batch_op.drop_column("join_key")
