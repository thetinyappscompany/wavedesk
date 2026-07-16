"""R7 — behavior tests for the parity-fill handlers (CSV import, onboarding
status, sessions, admin actions, webhook update/redeliver)."""

import uuid

import pytest

from tests.helpers import make_contact


@pytest.fixture
def authed(client, login, db):
    user = login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "R7 WS"},
    )
    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws, user


def _call(client, dotted, expect=200, headers=None, **params):
    r = client.post(f"/api/method/{dotted}", json=params, headers=headers or {})
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


def test_csv_import_creates_and_merges(authed, db):
    client, ws, _ = authed
    make_contact(db, ws, "919444400001", full_name="Old")
    csv = "phone,name,email\n919444400001,New Name,new@x.test\n919444400002,Fresh,f@x.test\n"
    out = _call(client, "wavedesk.api.contacts.import_contacts", csv_content=csv)
    assert out["status"] == "completed"
    status = _call(client, "wavedesk.api.contacts.import_status", import_name=out["import"])
    assert status["created"] == 1
    assert status["updated"] == 1
    listed = _call(client, "wavedesk.api.contacts.list_contacts", search="9444400001")
    assert listed["contacts"][0]["full_name"] == "New Name"  # CSV won


def test_onboarding_status_progression(client, login, db):
    login()
    st = _call(client, "wavedesk.api.onboarding.onboarding_status")
    assert st["has_workspace"] is False
    _call(client, "wavedesk.api.onboarding.create_workspace", workspace_name="Onb")
    st = _call(client, "wavedesk.api.onboarding.onboarding_status")
    assert st["has_workspace"] is True
    assert st["step"] == "connect_number"


def test_session_revoke_others(authed, db):
    client, ws, user = authed
    from app import sessions

    other = sessions.create(str(user.id), user.email)  # a second device
    assert other in sessions.user_sids(str(user.id))
    out = _call(client, "wavedesk.api.security.revoke_other_sessions")
    assert out["revoked"] >= 1
    assert sessions.get(other) is None  # the other device is signed out
    assert _call(client, "frappe.auth.get_logged_user") == user.email  # I stay in


def test_admin_workspace_detail_and_unsuspend(authed, db):
    client, ws, user = authed
    db.get(type(user), user.id).is_platform_admin = True
    db.commit()
    detail = _call(client, "wavedesk.api.admin.workspace_detail", workspace=str(ws.id))
    assert detail["workspace_name"] == "R7 WS"
    from app import admin

    admin.suspend(db, ws.id, True)
    db.commit()
    _call(client, "wavedesk.api.admin.unsuspend_workspace", workspace=str(ws.id))
    db.expire_all()
    from app.models import Workspace

    assert not (db.get(Workspace, ws.id).settings or {}).get("suspended")


def test_webhook_update_and_redeliver(authed, db, monkeypatch):
    client, ws, _ = authed
    ep = _call(client, "wavedesk.api.webhooks.create_endpoint",
               url="https://a.test/h", events=["message.received"])
    _call(client, "wavedesk.api.webhooks.update_endpoint",
          endpoint=ep["name"], url="https://b.test/h", enabled=False)
    listed = _call(client, "wavedesk.api.webhooks.list_endpoints")
    assert listed[0]["url"] == "https://b.test/h"
    assert listed[0]["enabled"] is False
    # redeliver an existing delivery
    from app.models import WebhookDelivery

    delivery = WebhookDelivery(workspace_id=ws.id, endpoint_id=uuid.UUID(ep["name"]),
                               event="message.received", payload={"x": 1}, status="failed")
    db.add(delivery)
    db.commit()
    import app.webhooks as wh

    monkeypatch.setattr(wh.httpx, "post",
                        lambda url, **kw: type("R", (), {"status_code": 200})())
    out = _call(client, "wavedesk.api.webhooks.redeliver", delivery=str(delivery.id))
    assert out["redelivered"] == str(delivery.id)
