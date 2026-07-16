"""R1 acceptance — wa:events consumer: exactly-once, extraction, poison."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Chat, Contact, Message
from app.pipeline import consumer
from tests.helpers import baileys_event, make_number, make_workspace


@pytest.fixture
def stream():
    return f"wa:events:test:{uuid.uuid4().hex[:8]}"


@pytest.fixture
def r():
    return consumer.get_redis()


def _drain(r, stream, runs: int = 1) -> int:
    total = 0
    for _ in range(runs):
        total += consumer.process_wa_events(stream=stream, r=r)
    return total


def test_inbound_dm_creates_contact_chat_message(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    wa_chat = "919876500001@s.whatsapp.net"
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, wa_chat, "namaste", push_name="Riya"
    )})
    assert _drain(r, stream) == 1

    contact = db.execute(select(Contact).where(Contact.workspace_id == ws.id)).scalar_one()
    assert contact.phone == "919876500001"
    assert contact.full_name == "Riya"
    chat = db.execute(select(Chat).where(Chat.workspace_id == ws.id)).scalar_one()
    assert chat.chat_type == "dm"
    assert chat.number_id == number.id  # back-linked for replies
    assert chat.unread_count == 1
    msg = db.execute(select(Message).where(Message.workspace_id == ws.id)).scalar_one()
    assert msg.direction == "in"
    assert msg.body == "namaste"


def test_redelivery_is_exactly_once(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    event = baileys_event(ws.id, number.session_ref, "919876500002@s.whatsapp.net",
                          "hi", wa_message_id="WAMID.DUP1")
    r.xadd(stream, {"event": event})
    r.xadd(stream, {"event": event})  # gateway redelivery
    _drain(r, stream)
    count = db.execute(
        select(Message).where(Message.workspace_id == ws.id)
    ).scalars().all()
    assert len(count) == 1


def test_from_me_is_outbound_and_no_unread(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "919876500003@s.whatsapp.net", "reply", from_me=True
    )})
    _drain(r, stream)
    msg = db.execute(select(Message).where(Message.workspace_id == ws.id)).scalar_one()
    assert msg.direction == "out"
    chat = db.execute(select(Chat).where(Chat.workspace_id == ws.id)).scalar_one()
    assert chat.unread_count == 0


def test_status_broadcast_ignored(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "status@broadcast", "story"
    )})
    _drain(r, stream)
    assert db.execute(select(Message).where(Message.workspace_id == ws.id)).first() is None


def test_group_message_makes_group_chat_without_contact(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, f"g{uuid.uuid4().hex[:8]}@g.us", "group hello"
    )})
    _drain(r, stream)
    chat = db.execute(select(Chat).where(Chat.workspace_id == ws.id)).scalar_one()
    assert chat.chat_type == "group"
    assert db.execute(select(Contact).where(Contact.workspace_id == ws.id)).first() is None


def test_inbound_reopens_resolved_chat(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    wa_chat = "919876500004@s.whatsapp.net"
    r.xadd(stream, {"event": baileys_event(ws.id, number.session_ref, wa_chat, "first")})
    _drain(r, stream)
    chat = db.execute(select(Chat).where(Chat.workspace_id == ws.id)).scalar_one()
    chat.status = "resolved"
    db.commit()
    r.xadd(stream, {"event": baileys_event(ws.id, number.session_ref, wa_chat, "again")})
    _drain(r, stream)
    db.refresh(chat)
    assert chat.status == "open"


def test_bad_entry_parks_on_poison_after_retries(db, r, stream):
    r.xadd(stream, {"event": "{not json"})
    _drain(r, stream, runs=consumer.MAX_DELIVERIES)
    poison = r.xrange(stream + consumer.POISON_SUFFIX)
    assert len(poison) == 1
    # group is drained — nothing pending anymore
    assert consumer.process_wa_events(stream=stream, r=r) == 0
