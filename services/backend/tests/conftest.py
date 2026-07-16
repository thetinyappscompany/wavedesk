"""Test rig: real Postgres + real Redis (same discipline as the old suite)."""

import os
import uuid

# Point the app at the test database BEFORE any app import.
os.environ.setdefault(
    "WD_DATABASE_URL",
    "postgresql+psycopg://postgres:wavedesk_pg@localhost:5432/wavedesk_backend_test",
)

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.db import get_engine
from app.main import create_app
from app.models import Base, User
from app.security import hash_password

_ADMIN_URL = "postgresql://postgres:wavedesk_pg@localhost:5432/postgres"
_TEST_DB = "wavedesk_backend_test"


def _ensure_database() -> None:
    with psycopg.connect(_ADMIN_URL, autocommit=True) as conn:
        exists = conn.execute(
            "select 1 from pg_database where datname = %s", (_TEST_DB,)
        ).fetchone()
        if not exists:
            conn.execute(f'create database "{_TEST_DB}"')


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _ensure_database()
    Base.metadata.create_all(get_engine())
    yield
    Base.metadata.drop_all(get_engine())


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def db():
    from app.db import get_sessionmaker

    session = get_sessionmaker()()
    yield session
    session.close()


@pytest.fixture
def make_user(db):
    def _make(password: str = "s3cret-pass") -> User:
        user = User(
            email=f"u{uuid.uuid4().hex[:10]}@wavedesk.test",
            first_name="Test",
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def login(client, make_user):
    """Create a user and log the TestClient in; returns the user."""

    def _login():
        user = make_user()
        r = client.post("/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"})
        assert r.status_code == 200, r.text
        return user

    return _login
