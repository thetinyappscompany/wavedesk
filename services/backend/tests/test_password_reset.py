"""Password recovery — public forgot-password flow + the platform-admin
"send reset link" path. Covers the security properties, not just the happy
path: no account enumeration, hashed-at-rest tokens, single use, expiry,
session invalidation, and admin-only gating."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import mailer, passwords, sessions
from app.models import PasswordResetToken, User
from app.security import verify_password

_LINK_RE = re.compile(r"/reset-password\?token=([A-Za-z0-9_\-]+)")


@pytest.fixture
def mailbox(monkeypatch):
    """Capture outgoing mail instead of talking to SMTP."""
    sent: list[dict] = []

    def _send(to: str, subject: str, body: str) -> bool:
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(mailer, "send", _send)
    return sent


@pytest.fixture
def no_rate_limit(monkeypatch):
    """The limiter is exercised in its own test; every other test would
    otherwise share the TestClient's IP budget and flake."""
    monkeypatch.setattr(passwords, "rate_limit_ok", lambda *a, **k: True)


def _call(client, dotted, expect=200, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == expect, r.text
    return r.json().get("message") if expect == 200 else r.json()


def _token_from(mailbox: list[dict]) -> str:
    match = _LINK_RE.search(mailbox[-1]["body"])
    assert match, mailbox[-1]["body"]
    return match.group(1)


# --- public forgot-password ---------------------------------------------------


def test_request_emails_a_working_reset_link(client, make_user, db, mailbox, no_rate_limit):
    user = make_user()
    out = _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    assert out["ok"] is True
    assert mailbox and mailbox[-1]["to"] == user.email

    token = _token_from(mailbox)
    _call(client, "wavedesk.api.auth.reset_password", token=token, password="brand-new-pass")

    db.expire_all()
    refreshed = db.get(User, user.id)
    assert verify_password("brand-new-pass", refreshed.password_hash)
    assert not verify_password("s3cret-pass", refreshed.password_hash)
    # the new password actually logs in
    r = client.post("/api/method/login", json={"usr": user.email, "pwd": "brand-new-pass"})
    assert r.status_code == 200


def test_unknown_email_is_indistinguishable(client, db, mailbox, no_rate_limit):
    """Same body, no token, no email — the endpoint is not an enumeration
    oracle."""
    known = _call(client, "wavedesk.api.auth.request_password_reset",
                  email="nobody-here@wavedesk.test")
    assert known == {
        "ok": True,
        "detail": "If that email has a WaveDesk account, a reset link is on its way.",
    }
    assert mailbox == []


def test_token_is_stored_hashed_not_plaintext(client, make_user, db, mailbox, no_rate_limit):
    user = make_user()
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    token = _token_from(mailbox)
    row = db.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    ).scalar_one()
    assert row.token_hash != token
    assert len(row.token_hash) == 64  # sha256 hex


def test_link_is_single_use(client, make_user, mailbox, no_rate_limit):
    user = make_user()
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    token = _token_from(mailbox)
    _call(client, "wavedesk.api.auth.reset_password", token=token, password="first-pass-99")
    _call(client, "wavedesk.api.auth.reset_password", expect=400,
          token=token, password="second-pass-99")


def test_issuing_again_invalidates_the_previous_link(client, make_user, mailbox, no_rate_limit):
    user = make_user()
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    first = _token_from(mailbox)
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    second = _token_from(mailbox)
    assert first != second
    _call(client, "wavedesk.api.auth.reset_password", expect=400,
          token=first, password="stale-link-pass")
    _call(client, "wavedesk.api.auth.reset_password", token=second, password="fresh-link-pass")


def test_expired_link_is_rejected(client, make_user, db, mailbox, no_rate_limit):
    user = make_user()
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    token = _token_from(mailbox)
    row = db.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    ).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    _call(client, "wavedesk.api.auth.reset_password", expect=400,
          token=token, password="too-late-pass")


def test_reset_destroys_every_existing_session(client, make_user, mailbox, no_rate_limit):
    """Recovery implies possible compromise — old sessions must not survive."""
    user = make_user()
    sid_a = sessions.create(str(user.id), user.email)
    sid_b = sessions.create(str(user.id), user.email)
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    _call(client, "wavedesk.api.auth.reset_password",
          token=_token_from(mailbox), password="rotated-pass-1")
    assert sessions.get(sid_a) is None
    assert sessions.get(sid_b) is None


def test_short_password_rejected(client, make_user, mailbox, no_rate_limit):
    user = make_user()
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    _call(client, "wavedesk.api.auth.reset_password", expect=400,
          token=_token_from(mailbox), password="short")


def test_disabled_account_gets_no_link(client, make_user, db, mailbox, no_rate_limit):
    user = make_user()
    user.enabled = False
    db.commit()
    _call(client, "wavedesk.api.auth.request_password_reset", email=user.email)
    assert mailbox == []


def test_rate_limiter_caps_requests_per_email():
    email = f"rl-{uuid.uuid4().hex[:8]}@wavedesk.test"
    ip = f"10.0.0.{uuid.uuid4().int % 250}"
    allowed = [passwords.rate_limit_ok(email, ip) for _ in range(passwords.MAX_PER_EMAIL_PER_HOUR)]
    assert all(allowed)
    assert passwords.rate_limit_ok(email, ip) is False


# --- platform-admin surface ---------------------------------------------------


@pytest.fixture
def admin_client(client, make_user, db):
    user = make_user()
    user.is_platform_admin = True
    db.commit()
    r = client.post("/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"})
    assert r.status_code == 200
    return client, user


def test_admin_lists_every_account_with_workspaces(admin_client, make_user, db):
    client, admin_user = admin_client
    member = make_user()
    from app.models import WorkspaceMember
    from tests.helpers import make_workspace

    ws = make_workspace(db, name="Acme Admin Test")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role="Owner"))
    db.commit()

    users = _call(client, "wavedesk.api.admin.list_users")["users"]
    emails = {u["email"] for u in users}
    assert member.email in emails and admin_user.email in emails
    row = next(u for u in users if u["email"] == member.email)
    assert row["workspaces"] == [{"workspace_name": "Acme Admin Test", "role": "Owner"}]

    # search narrows by email
    found = _call(client, "wavedesk.api.admin.list_users", search=member.email)["users"]
    assert [u["email"] for u in found] == [member.email]


def test_admin_send_reset_emails_the_user(admin_client, make_user, mailbox):
    client, _ = admin_client
    target = make_user()
    out = _call(client, "wavedesk.api.admin.send_password_reset", user=str(target.id))
    assert out["delivered"] is True
    assert out["link"] is None  # delivered → the link stays in their inbox
    assert mailbox[-1]["to"] == target.email
    # and the emailed link works
    _call(client, "wavedesk.api.auth.reset_password",
          token=_token_from(mailbox), password="admin-issued-pass")


def test_admin_send_reset_returns_link_when_smtp_unconfigured(admin_client, make_user, monkeypatch):
    """Escape hatch before SMTP is set up: the operator can hand over the link."""
    client, _ = admin_client
    target = make_user()
    monkeypatch.setattr(mailer, "send", lambda *a, **k: False)
    out = _call(client, "wavedesk.api.admin.send_password_reset", email=target.email)
    assert out["delivered"] is False
    assert "/reset-password?token=" in out["link"]


def test_admin_endpoints_refuse_non_admins(client, login, make_user):
    login()  # ordinary user
    target = make_user()
    _call(client, "wavedesk.api.admin.list_users", expect=403)
    _call(client, "wavedesk.api.admin.send_password_reset", expect=403, user=str(target.id))


def test_admin_send_reset_unknown_user_404(admin_client):
    client, _ = admin_client
    _call(client, "wavedesk.api.admin.send_password_reset", expect=404,
          email="ghost@wavedesk.test")
