"""Alembic environment.

The connection URL is never written into alembic.ini - it is read from the
application's own config, so there is exactly one place a database URL lives
and no chance of a migration being applied to the wrong database because two
files disagreed.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import DATABASE_URL, IS_SQLITE  # noqa: E402
from app.database import Base  # noqa: E402
from app.dbtypes import UtcDateTime  # noqa: E402
from app import models  # noqa: E402,F401  (imported for its side effect: registering the tables)

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render UtcDateTime as the plain SQLAlchemy type it wraps.

    Migrations must not import application code: a migration is a historical
    record of what the schema was, and it has to keep running years later even
    if `app.dbtypes` has been renamed or deleted. UtcDateTime only adds Python
    -side normalisation - the column it produces is an ordinary
    `DateTime(timezone=True)` - so emitting that keeps the migration
    self-contained without changing the DDL by one character.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        autogen_context.imports.add("import sqlalchemy as sa")
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_item=render_item,
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead. Harmless on Postgres, essential for the offline
        # fallback.
        render_as_batch=IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_item=render_item,
            render_as_batch=IS_SQLITE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
