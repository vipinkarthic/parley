"""password_changed_at, so a password change can revoke issued tokens

Revision ID: b1c4e7a90d31
Revises: a89f8a673066
Create Date: 2026-09-14

Access tokens carry no jti and there is no denylist, so until now nothing
could invalidate one before it expired - including changing the password it
was obtained with. This column is the revocation point: a token whose `iat`
is not after it is refused.

Backfilled to the row's own created_at (falling back to now) rather than to
now for everyone, so existing sessions are not all logged out by the upgrade.
"""
import sqlalchemy as sa
from alembic import op

revision = "b1c4e7a90d31"
down_revision = "a89f8a673066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE users SET password_changed_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
        "WHERE password_changed_at IS NULL"
    )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("password_changed_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_changed_at")
