"""R1 acceptance — wa:events consumer: exactly-once, extraction, poison."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Chat, Contact, Message
from app.pipeline import consumer
from tests.helpers import baileys_event, make_contact, make_number, make_workspace


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


def test_failing_inbound_hook_does_not_lose_message(db, r, stream, monkeypatch):
    """A best-effort inbound hook that raises (aborting its own txn on PG) must
    not lose the already-persisted message or poison the event."""
    ws = make_workspace(db)
    number = make_number(db, ws)
    from app import automation

    def boom(hook_db, *args, **kwargs):
        hook_db.execute(select(Message))  # issue SQL, then abort the txn
        raise RuntimeError("hook exploded")

    monkeypatch.setattr(automation, "run_trigger", boom)
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "919876500009@s.whatsapp.net", "hi", push_name="X"
    )})
    assert _drain(r, stream) == 1  # event acked despite the hook failure
    msg = db.execute(select(Message).where(Message.workspace_id == ws.id)).scalar_one()
    assert msg.body == "hi"  # message persisted, not rolled back with the hook


def test_push_name_backfills_nameless_contact(db, r, stream):
    """A contact created without a name (e.g. from an outbound chat) gets the
    WhatsApp profile name on the next inbound message — the inbox must not
    title DMs with raw digits forever. An existing name is never overwritten."""
    ws = make_workspace(db)
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919876500042")  # nameless
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "919876500042@s.whatsapp.net", "hello",
        push_name="Riya Sharma",
    )})
    _drain(r, stream)
    db.expire_all()
    assert db.get(type(contact), contact.id).full_name == "Riya Sharma"

    # A later message with a different profile name must NOT clobber it.
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "919876500042@s.whatsapp.net", "again",
        push_name="R. Sharma (new)",
    )})
    _drain(r, stream)
    db.expire_all()
    assert db.get(type(contact), contact.id).full_name == "Riya Sharma"


def test_group_chat_links_to_late_registry_row(db, r, stream):
    """A chat that predates its Group registry row (sync failed/ran later) heals
    its group link on the next inbound message, so the inbox shows the real
    subject instead of the raw @g.us jid."""
    from app.models import Group

    ws = make_workspace(db)
    number = make_number(db, ws)
    wa_group = "120363000111222333@g.us"
    # Message first → chat exists with NO group link (registry empty).
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, wa_group, "pre-sync chatter",
        participant="919876500043@s.whatsapp.net",
    )})
    _drain(r, stream)
    chat = db.execute(select(Chat).where(
        Chat.workspace_id == ws.id, Chat.wa_chat_id == wa_group)).scalar_one()
    assert chat.group_id is None

    # Registry row appears later WITHOUT a group.upsert event reaching the
    # backlink path (e.g. imported/refetched) — the next message heals the link.
    group = Group(workspace_id=ws.id, wa_group_id=wa_group, subject="Traders Hub")
    db.add(group)
    db.commit()
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, wa_group, "post-sync chatter",
        participant="919876500043@s.whatsapp.net",
    )})
    _drain(r, stream)
    db.expire_all()
    assert chat.group_id == group.id
