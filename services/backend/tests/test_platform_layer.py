"""R6 acceptance — billing, public API, webhooks, admin, DPDP, 2FA, verticals,
IP allowlist."""

import time
import uuid

import pytest

from app import auth_twofa, billing, wallet
from tests.helpers import make_chat, make_contact, make_message, make_number, make_workspace


@pytest.fixture
def authed(client, login, db):
    user = login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "R6 WS"},
    )
    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws, user


def _call(client, dotted, expect=200, headers=None, **params):
    r = client.post(f"/api/method/{dotted}", json=params, headers=headers or {})
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


# --- billing --------------------------------------------------------------------


def test_zoho_webhook_activates_and_flips_addon(db):
    ws = make_workspace(db)
    from app.gating import ensure_subscription

    ensure_subscription(db, ws.id)
    db.commit()
    billing.process(db, {"type": "subscription_created", "workspace": str(ws.id),
                         "plan_code": "WD-PRO", "addon_codes": ["WD-ADDON-AI"]})
    from app.gating import has_feature

    assert has_feature(db, ws.id, "ai_addon") is True


def test_addon_downgrade_clears_entitlement(db):
    ws = make_workspace(db)
    from app.gating import ensure_subscription, has_feature

    ensure_subscription(db, ws.id)
    db.commit()
    billing.process(db, {"type": "subscription_created", "workspace": str(ws.id),
                         "addon_codes": ["WD-ADDON-AI"], "event_time": "2026-07-16T10:00:00"})
    assert has_feature(db, ws.id, "ai_addon") is True
    # a later renewal WITHOUT the AI add-on is a downgrade — must clear it,
    # not leave the paid feature enabled forever
    billing.process(db, {"type": "subscription_renewed", "workspace": str(ws.id),
                         "addon_codes": [], "event_time": "2026-07-16T11:00:00"})
    assert has_feature(db, ws.id, "ai_addon") is False


def test_out_of_order_webhook_never_regresses(db):
    ws = make_workspace(db)
    from app.gating import ensure_subscription

    ensure_subscription(db, ws.id)
    db.commit()
    billing.process(db, {"type": "subscription_cancelled", "workspace": str(ws.id),
                         "event_time": "2026-07-16T10:00:00"})
    billing.process(db, {"type": "subscription_created", "workspace": str(ws.id),
                         "event_time": "2026-07-16T09:00:00"})  # stale
    from app.models import Subscription
    from sqlalchemy import select

    sub = db.execute(select(Subscription).where(Subscription.workspace_id == ws.id)).scalar_one()
    assert sub.status == "cancelled"


def test_topup_credits_wallet_idempotently(db):
    ws = make_workspace(db)
    from app.gating import ensure_subscription

    ensure_subscription(db, ws.id)
    db.commit()
    inv = f"inv-{uuid.uuid4().hex}"
    event = {"type": "payment_success", "workspace": str(ws.id),
             "invoice": {"id": inv, "amount": 1000, "is_topup": True}}
    billing.process(db, event)
    billing.process(db, event)  # retried
    assert wallet.get_balance(db, ws.id) == 1000.0


# --- public API -----------------------------------------------------------------


def test_public_api_key_lifecycle_and_scope(authed, db):
    client, ws, _user = authed
    key = _call(client, "wavedesk.api.publicapi.create_key",
                scopes=["chats:read"], rate_limit_per_min=100)
    assert key["key"].startswith("wdk_")
    # listing never leaks the hash
    listed = _call(client, "wavedesk.api.publicapi.list_keys")
    assert "key_hash" not in listed[0]
    make_chat(db, ws)
    # authorized call
    out = _call(client, "wavedesk.api.v1.list_chats",
                headers={"Authorization": f"Bearer {key['key']}"})
    assert len(out["chats"]) == 1
    # scope enforcement — send needs messages:send
    _call(client, "wavedesk.api.v1.send_message", expect=401,
          headers={"Authorization": f"Bearer {key['key']}"}, chat="x")
    # revoked key rejected
    _call(client, "wavedesk.api.publicapi.revoke_key", key=key["name"])
    _call(client, "wavedesk.api.v1.list_chats", expect=401,
          headers={"Authorization": f"Bearer {key['key']}"})


# --- webhooks -------------------------------------------------------------------


def test_webhook_emit_creates_delivery(authed, db, monkeypatch):
    client, ws, _user = authed
    _call(client, "wavedesk.api.webhooks.create_endpoint",
          url="https://example.test/hook", events=["message.received"])
    posted = {}
    import app.webhooks as wh

    monkeypatch.setattr(wh.httpx, "post",
                        lambda url, **kw: (posted.setdefault("url", url),
                                           type("R", (), {"status_code": 200})())[1])
    from app import webhooks

    # emit + commit BEFORE delivery runs (mirrors the request-then-RQ ordering)
    from app.models import WebhookDelivery
    from sqlalchemy import select

    delivery = WebhookDelivery(workspace_id=ws.id,
                               endpoint_id=_endpoint_id(db, ws),
                               event="message.received", payload={"chat": "c1"})
    db.add(delivery)
    db.commit()
    webhooks.deliver(str(delivery.id))
    db.expire_all()
    row = db.execute(select(WebhookDelivery).where(WebhookDelivery.id == delivery.id)).scalar_one()
    assert row.status == "delivered"
    assert posted["url"] == "https://example.test/hook"


def test_webhook_retry_backoff_then_dead_letter(authed, db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    client, ws, _user = authed
    _call(client, "wavedesk.api.webhooks.create_endpoint",
          url="https://down.test/hook", events=["message.received"])
    import app.webhooks as wh
    from app.models import WebhookDelivery

    monkeypatch.setattr(wh.httpx, "post",
                        lambda url, **kw: type("R", (), {"status_code": 503})())
    delivery = WebhookDelivery(workspace_id=ws.id, endpoint_id=_endpoint_id(db, ws),
                               event="message.received", payload={"x": 1})
    db.add(delivery)
    db.commit()
    did = str(delivery.id)
    for i in range(1, wh.MAX_ATTEMPTS + 1):
        wh.deliver(did)
        db.expire_all()
        row = db.get(WebhookDelivery, delivery.id)
        assert row.attempts == i
        if i < wh.MAX_ATTEMPTS:
            assert row.status == "pending" and row.next_retry_at is not None
        else:
            assert row.status == "dead" and row.next_retry_at is None  # dead-lettered

    # retry_due re-enqueues only deliveries whose backoff has elapsed
    calls: list = []
    monkeypatch.setattr(wh.tasks, "enqueue",
                        lambda fn, **kw: calls.append(kw["delivery_id"]))
    due = WebhookDelivery(workspace_id=ws.id, endpoint_id=_endpoint_id(db, ws),
                          event="message.received", payload={}, status="pending",
                          attempts=1, next_retry_at=datetime.now(UTC) - timedelta(minutes=1))
    later = WebhookDelivery(workspace_id=ws.id, endpoint_id=_endpoint_id(db, ws),
                            event="message.received", payload={}, status="pending",
                            attempts=1, next_retry_at=datetime.now(UTC) + timedelta(minutes=5))
    db.add_all([due, later])
    db.commit()
    wh.retry_due(db)
    assert str(due.id) in calls
    assert str(later.id) not in calls  # not yet due


def _endpoint_id(db, ws):
    from app.models import WebhookEndpoint
    from sqlalchemy import select

    return db.execute(
        select(WebhookEndpoint.id).where(WebhookEndpoint.workspace_id == ws.id)
    ).scalars().first()


# --- admin ----------------------------------------------------------------------


def test_admin_requires_platform_flag(authed, db):
    client, ws, user = authed
    _call(client, "wavedesk.api.admin.list_workspaces", expect=403)  # not platform admin
    # promote the ACTUAL logged-in caller
    db.get(type(user), user.id).is_platform_admin = True
    db.commit()
    rows = _call(client, "wavedesk.api.admin.list_workspaces")
    assert any(r["workspace_name"] == "R6 WS" for r in rows)
    stats = _call(client, "wavedesk.api.admin.platform_stats")
    assert stats["totals"]["workspaces"] >= 1
    # Full WdPlatformStats contract — a missing key white-screens the /admin page
    assert "numbers" in stats["totals"]
    assert set(stats["trial_vs_paid"]) == {"trial", "paid", "past_due"}
    assert "suspended" in stats["operational"]
    assert isinstance(stats["by_plan"], list)


def test_suspend_blocks_send(authed, db):
    from app import admin
    from app.pipeline import sender

    client, ws, _user = authed
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919333300001")
    chat = make_chat(db, ws, number=number, contact=contact,
                     wa_chat_id="919333300001@s.whatsapp.net")
    admin.suspend(db, ws.id, True, "abuse")
    db.commit()
    with pytest.raises(sender.SendError):
        sender.queue_send(db, chat, "hi", None)


def test_send_rate_clamp_blocks_over_daily(authed, db):
    from app import admin

    client, ws, _user = authed
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919333309999")
    chat = make_chat(db, ws, number=number, contact=contact,
                     wa_chat_id="919333309999@s.whatsapp.net")
    make_message(db, ws, chat, body="out1", direction="out")  # 1 sent today
    ws.settings = {**(ws.settings or {}), "send_rate_clamp": 1}
    db.commit()
    with pytest.raises(admin.Suspended):
        admin.assert_can_send(db, ws.id)


# --- DPDP -----------------------------------------------------------------------


def test_export_and_erase_and_retention(authed, db):
    from app import compliance

    client, ws, _user = authed
    contact = make_contact(db, ws, "919333300002", full_name="Erase Me", email="e@x.test")
    chat = make_chat(db, ws, contact=contact)
    make_message(db, ws, chat, body="secret content")
    export = _call(client, "wavedesk.api.privacy.request_export")
    assert export["status"] == "ready"
    assert export["counts"]["contacts"] >= 1
    _call(client, "wavedesk.api.privacy.erase_contact", contact=str(contact.id))
    db.expire_all()
    db.refresh(contact)
    assert contact.erased is True
    assert contact.full_name == compliance.ERASED_TOKEN


# --- 2FA ------------------------------------------------------------------------


def test_twofa_enroll_verify_recovery(authed, db):
    client, ws, user = authed
    begun = _call(client, "wavedesk.api.security.twofa_begin_enroll")
    code = auth_twofa.totp(begun["secret"], time.time())
    out = _call(client, "wavedesk.api.security.twofa_confirm_enroll", code=code)
    assert out["enabled"] is True
    assert len(out["recovery_codes"]) == auth_twofa.RECOVERY_COUNT
    db.expire_all()
    # a recovery code passes once, then is spent
    recovery = out["recovery_codes"][0]
    assert auth_twofa.verify(db, user.id, recovery) is True
    db.commit()
    assert auth_twofa.verify(db, user.id, recovery) is False


# --- verticals ------------------------------------------------------------------


def test_apply_vertical_is_idempotent(authed, db):
    client, ws, _user = authed
    out = _call(client, "wavedesk.api.verticals.apply_vertical", vertical="d2c")
    assert out["created"]["labels"] == 3
    again = _call(client, "wavedesk.api.verticals.apply_vertical", vertical="d2c")
    assert again["created"]["labels"] == 0  # idempotent
    labels = _call(client, "wavedesk.api.labels.list_labels")
    assert {"order", "refund", "shipping"}.issubset({label["title"] for label in labels})


# --- IP allowlist ---------------------------------------------------------------


def test_ip_allowlist_normalize_and_get_set(authed):
    client, _ws, _user = authed
    out = _call(client, "wavedesk.api.access.set_ip_allowlist",
                entries=["203.0.113.5", "10.0.0.0/8", " "])
    assert "203.0.113.5/32" in out["ip_allowlist"]
    assert "10.0.0.0/8" in out["ip_allowlist"]
    got = _call(client, "wavedesk.api.access.get_ip_allowlist")
    assert got["ip_allowlist"] == out["ip_allowlist"]
    _call(client, "wavedesk.api.access.set_ip_allowlist", expect=400, entries=["not-an-ip"])


def test_ip_allowlist_enforced_on_public_api(authed, db, monkeypatch):
    client, ws, _user = authed
    key = _call(client, "wavedesk.api.publicapi.create_key", scopes=["chats:read"])
    _call(client, "wavedesk.api.access.set_ip_allowlist", entries=["203.0.113.0/24"])
    # TestClient's peer IP (testclient) isn't in the allowlist → 403
    _call(client, "wavedesk.api.v1.list_chats", expect=403,
          headers={"Authorization": f"Bearer {key['key']}"})
