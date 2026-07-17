"""Profile + billing summary (Settings → Account / Billing tabs)."""

import uuid

from app import sessions
from app.models import WorkspaceMember


def _call(client, dotted, expect=200, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


def test_profile_get_update_and_password_change(client, login):
    user = login()
    prof = _call(client, "wavedesk.api.profile.get_profile")
    assert prof["email"] == user.email
    assert "is_platform_admin" in prof

    out = _call(client, "wavedesk.api.profile.update_profile", first_name="Asha")
    assert out["first_name"] == "Asha"

    # wrong current password → 403, short new password → 400
    _call(client, "wavedesk.api.profile.change_password", expect=403,
          current_password="wrong", new_password="brand-new-pass1")
    _call(client, "wavedesk.api.profile.change_password", expect=400,
          current_password="s3cret-pass", new_password="short")

    out = _call(client, "wavedesk.api.profile.change_password",
                current_password="s3cret-pass", new_password="brand-new-pass1")
    assert out["ok"] is True

    # The old password is dead; the new one logs in.
    client.cookies.clear()
    r = client.post("/api/method/login", json={"usr": user.email, "pwd": "s3cret-pass"})
    assert r.status_code == 401
    r = client.post("/api/method/login",
                    json={"usr": user.email, "pwd": "brand-new-pass1"})
    assert r.status_code == 200


def test_password_change_revokes_other_sessions(client, login):
    user = login()
    other_sid = sessions.create(str(user.id), user.email)  # a second device
    assert sessions.get(other_sid) is not None

    out = _call(client, "wavedesk.api.profile.change_password",
                current_password="s3cret-pass", new_password="brand-new-pass2")
    assert out["revoked_sessions"] >= 1
    assert sessions.get(other_sid) is None  # other device signed out
    # …but the session that changed the password stays logged in.
    assert _call(client, "wavedesk.api.profile.get_profile")["email"] == user.email


def test_billing_summary_manager_only(client, login, db, make_user):
    login()
    ws_id = _call(client, "wavedesk.api.onboarding.create_workspace",
                  workspace_name="Billing WS")["workspace"]

    out = _call(client, "wavedesk.api.billing.billing_summary")
    # Full WdBillingSummary contract (the Billing tab reads these keys)
    assert set(out) == {"plan", "status", "ai_addon", "current_period_end",
                        "wallet_balance"}
    assert out["status"] == "trialing"  # trial auto-provisioned at signup
    assert isinstance(out["wallet_balance"], int | float)

    # An Agent gets a 403 — billing is manager-only.
    agent = make_user()
    db.add(WorkspaceMember(workspace_id=uuid.UUID(ws_id), user_id=agent.id,
                           role="Agent"))
    db.commit()
    client.cookies.clear()
    r = client.post("/api/method/login",
                    json={"usr": agent.email, "pwd": "s3cret-pass"})
    assert r.status_code == 200  # login auto-binds the agent's workspace
    _call(client, "wavedesk.api.billing.billing_summary", expect=403)
