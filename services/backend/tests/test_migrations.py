"""Alembic guard: the initial migration applies cleanly to an empty database and
leaves NO drift versus the SQLAlchemy models. If someone adds/changes a model
without a matching migration, `compare_metadata` reports the diff and this fails
— the same discipline the old suite enforced with its DocType coverage test.
"""

import uuid
from pathlib import Path

import psycopg
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base

_ADMIN_URL = "postgresql://postgres:wavedesk_pg@localhost:5432/postgres"
_BACKEND = Path(__file__).resolve().parents[1]


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migrations_apply_and_match_models():
    scratch = f"wd_alembic_drift_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'create database "{scratch}"')
    url = f"postgresql+psycopg://postgres:wavedesk_pg@localhost:5432/{scratch}"
    engine = None
    try:
        # 1. Migrations apply cleanly to an empty DB.
        command.upgrade(_alembic_config(url), "head")

        # 2. The resulting schema matches the models exactly — no drift.
        engine = create_engine(url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diffs = compare_metadata(ctx, Base.metadata)
        assert diffs == [], f"model/migration drift — regenerate the migration: {diffs}"
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(_ADMIN_URL, autocommit=True) as conn:
            conn.execute(f'drop database if exists "{scratch}"')
