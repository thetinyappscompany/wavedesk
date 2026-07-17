"""Alembic environment — targets the app's SQLAlchemy metadata and reads the
database URL from app config (WD_DATABASE_URL), never from alembic.ini."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 — importing populates Base.metadata with every table
from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use an explicitly-provided URL if the caller set one (e.g. the drift-guard
# test points at a scratch DB); otherwise take the app's configured URL.
config.set_main_option(
    "sqlalchemy.url",
    config.get_main_option("sqlalchemy.url") or get_settings().database_url,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Read the RESOLVED url (explicit override wins) — never re-derive from
    # settings here, or offline/--sql mode silently ignores the override the
    # drift-guard test (and any scratch-DB caller) injects via set_main_option.
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
