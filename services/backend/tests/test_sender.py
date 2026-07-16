"""R1 acceptance — the protected send pipeline (gateway mocked)."""

import uuid as uuidlib

import pytest

from app import gateway
from app.models import Message
from app.pipeline import sender
from tests.helpers import make_chat, make_contact, make_number, make_workspace


@pytest.fixture
def rig(db):
    ws = make_workspace(db)
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919876600001")
    chat = make_chat(db, ws, number=number, contact=contact,
                     wa_chat_id="919876600001@s.whatsapp.net")
    return ws, number, chat


def test_send_delivers_via_gateway(db, rig, monkeypatch):
    _, number, chat = rig
    calls = []

    def fake_send(session_id, to, text):
        calls.append((session_id, to, text))
        return {"wa_message_id": "WAMID.OUT1"}

    monkeypatch.setattr(gateway, "send_session_message", fake_send)
    out = sender.queue_send(db, chat, "hello there", None)
    assert out["status"] == "queued"
    assert out["creation"]  # server timestamp surfaced

    db.expire_all()
    msg = db.get(Message, uuidlib.UUID(out["name"]))
    assert msg.status == "sent"
    assert msg.wa_message_id == "WAMID.OUT1"
    assert calls == [(number.session_ref, chat.wa_chat_id, "hello there")]
    db.refresh(chat)
    assert chat.first_response_at is not None  # first-reply analytics stamp


def test_gateway_failure_retries_then_fails(db, rig, monkeypatch):
    _, _, chat = rig
    attempts = []

    def always_down(session_id, to, text):
        attempts.append(1)
        raise gateway.GatewayError("down")

    monkeypatch.setattr(gateway, "send_session_message", always_down)
    out = sender.queue_send(db, chat, "doomed", None)

    db.expire_all()
    msg = db.get(Message, uuidlib.UUID(out["name"]))
    assert msg.status == "failed"
    assert len(attempts) == sender.MAX_DELIVERY_ATTEMPTS


def test_duplicate_job_is_noop(db, rig, monkeypatch):
    _, _, chat = rig
    calls = []
    monkeypatch.setattr(
        gateway, "send_session_message",
        lambda *a: (calls.append(1), {"wa_message_id": "W1"})[1],
    )
    out = sender.queue_send(db, chat, "once", None)
    sender.deliver_message(out["name"])  # replayed job
    assert len(calls) == 1  # flip-before-send made the replay a no-op


def test_retry_after_failure_succeeds(db, rig, monkeypatch):
    _, _, chat = rig
    monkeypatch.setattr(
        gateway, "send_session_message",
        lambda *a: (_ for _ in ()).throw(gateway.GatewayError("down")),
    )
    out = sender.queue_send(db, chat, "flaky", None)

    db.expire_all()
    msg = db.get(Message, uuidlib.UUID(out["name"]))
    assert msg.status == "failed"

    monkeypatch.setattr(
        gateway, "send_session_message", lambda *a: {"wa_message_id": "W2"}
    )
    sender.retry_send(db, msg)
    db.expire_all()
    msg = db.get(Message, uuidlib.UUID(out["name"]))
    assert msg.status == "sent"


def test_no_number_refuses(db, rig):
    ws, _, _ = rig
    orphan = make_chat(db, ws, wa_chat_id="919876600002@s.whatsapp.net")
    with pytest.raises(sender.SendError):
        sender.queue_send(db, orphan, "nope", None)
