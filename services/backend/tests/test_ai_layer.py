"""R5 acceptance — wallet, gating, AI provider/metering/crypto, copilot,
flagging, agent, leak guard."""

import uuid
from unittest.mock import patch

import pytest

from app import gating, wallet
from app.ai import provider
from tests.helpers import make_chat, make_workspace


@pytest.fixture
def authed(client, login, db):
    login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "R5 WS"},
    )
    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws


def _call(client, dotted, expect=200, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


def _enable_ai(db, ws):
    from app.models import Subscription

    sub = db.execute(
        __import__("sqlalchemy").select(Subscription).where(Subscription.workspace_id == ws.id)
    ).scalar_one()
    sub.addons = {"ai_addon": True}
    db.commit()


class _FakeResp:
    def __init__(self, text, in_tok=1000, out_tok=100):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": in_tok, "output_tokens": out_tok})()


class _FakeClient:
    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        self.last = kwargs
        return _FakeResp(self._text)


# --- wallet -------------------------------------------------------------------


def test_wallet_append_only_idempotent(db):
    ws = make_workspace(db)
    wallet.credit(db, ws.id, 100.0, "topup", "k-credit-1")
    wallet.credit(db, ws.id, 100.0, "topup", "k-credit-1")  # retried
    assert wallet.get_balance(db, ws.id) == 100.0
    wallet.charge(db, ws.id, 40.0, "spend", "k-charge-1")
    wallet.charge(db, ws.id, 40.0, "spend", "k-charge-1")  # retried
    assert wallet.get_balance(db, ws.id) == 60.0
    from app.models import WalletTransaction

    rows = db.execute(
        __import__("sqlalchemy").select(WalletTransaction).where(
            WalletTransaction.workspace_id == ws.id
        )
    ).scalars().all()
    assert len(rows) == 2  # exactly one per key


def test_charge_rejected_when_insufficient(db):
    ws = make_workspace(db)
    with pytest.raises(wallet.InsufficientBalance):
        wallet.charge(db, ws.id, 10.0, "x", "k")


# --- gating -------------------------------------------------------------------


def test_trial_auto_provision_and_gate(db):
    ws = make_workspace(db)
    gating.ensure_subscription(db, ws.id)
    db.commit()
    assert gating.has_feature(db, ws.id, "ai_addon") is False
    _enable_ai(db, ws)
    assert gating.has_feature(db, ws.id, "ai_addon") is True


# --- provider gate + metering -------------------------------------------------


def test_provider_gated_without_addon(db):
    ws = make_workspace(db)
    gating.ensure_subscription(db, ws.id)
    db.commit()
    with pytest.raises(provider.FeatureNotAvailable):
        provider.complete(db, ws.id, task="reply", messages=[], source="x", idempotency_key="k")


def test_pooled_call_meters_within_allowance(db, monkeypatch):
    ws = make_workspace(db)
    gating.ensure_subscription(db, ws.id)
    _enable_ai(db, ws)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-pool")
    fake = _FakeClient("hello")
    with patch.object(provider, "_client", lambda key: fake):
        out = provider.complete(db, ws.id, task="reply", messages=[{"role": "user", "content": "hi"}],
                                source="agent:reply", idempotency_key="ai-1")
    assert out["path"] == "pooled"
    # small cost stays inside the $5 allowance → no wallet charge
    assert wallet.get_balance(db, ws.id) == 0.0
    from app.models import UsageRecord

    rows = db.execute(
        __import__("sqlalchemy").select(UsageRecord).where(UsageRecord.workspace_id == ws.id)
    ).scalars().all()
    assert len(rows) == 1


def test_metering_retry_is_idempotent(db, monkeypatch):
    ws = make_workspace(db)
    gating.ensure_subscription(db, ws.id)
    _enable_ai(db, ws)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-pool")
    fake = _FakeClient("x")
    with patch.object(provider, "_client", lambda key: fake):
        provider.complete(db, ws.id, task="reply", messages=[{"role": "user", "content": "hi"}],
                          source="agent:reply", idempotency_key="dup-key")
        provider.complete(db, ws.id, task="reply", messages=[{"role": "user", "content": "hi"}],
                          source="agent:reply", idempotency_key="dup-key")
    from app.models import UsageRecord

    rows = db.execute(
        __import__("sqlalchemy").select(UsageRecord).where(
            UsageRecord.idempotency_key == "dup-key"
        )
    ).scalars().all()
    assert len(rows) == 1


def test_kill_switch_blocks(db, monkeypatch):
    ws = make_workspace(db)
    gating.ensure_subscription(db, ws.id)
    from app.models import Subscription

    sub = db.execute(
        __import__("sqlalchemy").select(Subscription).where(Subscription.workspace_id == ws.id)
    ).scalar_one()
    sub.addons = {"ai_addon": True, "ai_kill_switch": True}
    db.commit()
    with pytest.raises(provider.AIKillSwitchOn):
        provider.complete(db, ws.id, task="reply", messages=[], source="x", idempotency_key="k")


# --- crypto fail-closed -------------------------------------------------------


def test_crypto_roundtrip_and_fail_closed(monkeypatch):
    from app.ai import crypto

    assert crypto.decrypt(crypto.encrypt("byok-secret")) == "byok-secret"  # dev/test path
    monkeypatch.delenv("WD_DEV", raising=False)
    monkeypatch.delenv("WD_AI_SECRET", raising=False)
    # WD_TASK_INLINE is an ops flag (run RQ inline), NOT a dev signal — it must
    # NOT authorize the weak derived key. Only WD_DEV does.
    monkeypatch.setenv("WD_TASK_INLINE", "1")
    with pytest.raises(RuntimeError):
        crypto.encrypt("x")


def test_metering_settles_over_allowance_with_empty_wallet(db):
    """A model call that overruns both the allowance and the wallet must still
    be recorded (settled) — not raise and drop the customer's paid-for reply."""
    from app.ai import metering

    ws = make_workspace(db)  # empty wallet, no top-up
    out = metering.record_and_charge(
        db, ws.id, "claude-sonnet-5", input_tokens=5_000_000, output_tokens=5_000_000,
        source="agent:reply", idempotency_key="boundary-1",
    )
    assert out["overflow_usd"] > 0
    # cost recorded (5*3 + 5*15 = $90), wallet overdrawn rather than refused
    assert metering.consumed_usd(db, ws.id, metering.current_period()) >= 90
    assert wallet.get_balance(db, ws.id) < 0
    # the overdraft now pauses the NEXT call
    assert metering.is_available(db, ws.id) is False


# --- API leak guard -----------------------------------------------------------


def test_usage_meter_never_leaks_confidential(authed, db):
    client, ws = authed
    _enable_ai(db, ws)
    meter = _call(client, "wavedesk.api.ai.usage_meter")
    confidential = {"model_rates", "markup_multiplier", "fx_rate_inr_per_usd",
                    "fx_buffer_pct", "usd", "tokens", "input_tokens"}
    assert confidential.isdisjoint(meter.keys())
    assert set(meter.keys()) == {"allowance_used_pct", "credits_balance_inr"}


# --- copilot API --------------------------------------------------------------


def test_copilot_gated_and_works(authed, db, monkeypatch):
    client, ws = authed
    chat = make_chat(db, ws)
    # without addon → 403
    _call(client, "wavedesk.api.copilot.suggest_reply", chat=str(chat.id), expect=403)
    _enable_ai(db, ws)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-pool")
    fake = _FakeClient("How can I help you today?")
    with patch.object(provider, "_client", lambda key: fake):
        out = _call(client, "wavedesk.api.copilot.suggest_reply", chat=str(chat.id))
    assert out["text"] == "How can I help you today?"


# --- flagging via consumer ----------------------------------------------------


def test_ai_flagging_flags_inbound(authed, db, monkeypatch):
    from app.pipeline import consumer
    from tests.helpers import baileys_event, make_number

    client, ws = authed
    _enable_ai(db, ws)
    number = make_number(db, ws)
    _call(client, "wavedesk.api.flagging.create_rule",
          flag_key="angry", label="Angry customer", prompt="customer is upset")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-pool")
    fake = _FakeClient('["angry"]')
    r = consumer.get_redis()
    stream = f"wa:events:test:{uuid.uuid4().hex[:8]}"
    with patch.object(provider, "_client", lambda key: fake):
        r.xadd(stream, {"event": baileys_event(
            ws.id, number.session_ref, "g-flag@g.us", "this is terrible service"
        )})
        consumer.process_wa_events(stream=stream, r=r)
    from app.models import Message

    msg = db.execute(
        __import__("sqlalchemy").select(Message).where(Message.workspace_id == ws.id)
    ).scalar_one()
    assert msg.flagged is True
    assert "Angry customer" in msg.flag_reason


# --- agent handoff (no token spent below threshold) ---------------------------


def test_agent_handoff_below_threshold(authed, db, monkeypatch):
    from app.ai import agent as ai_agent
    from app.ai import rag

    client, ws = authed
    _enable_ai(db, ws)
    _call(client, "wavedesk.api.agent.update_agent_config", enabled=True, confidence_threshold=0.6)
    with patch.object(rag, "search", lambda w, q, top_k=rag.TOP_K: [{"text": "x", "doc": "d", "score": 0.2}]), \
         patch.object(provider, "complete") as comp:
        out = ai_agent.answer(db, ws.id, "unrelated question")
    assert out["action"] == "handoff"
    comp.assert_not_called()  # no token spent on a handoff
