"""Collab suite — private notes, chat priority, macros, contact notes,
auto-resolve idle chats (Chatwoot-parity features)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Chat, Label, Message, Workspace, WorkspaceMember
from tests.helpers import make_chat, make_contact, make_workspace


@pytest.fixture
def authed(client, login, db):
    login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "Collab WS"},
    )
    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws


def _call(client, dotted, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == 200, r.text
    return r.json()["message"]


def _login_as_agent(client, db, make_user, ws):
    agent = make_user()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=agent.id, role="Agent"))
    db.commit()
    client.cookies.clear()
    r = client.post("/api/method/login", json={"usr": agent.email, "pwd": "s3cret-pass"})
    assert r.status_code == 200
    _call(client, "wavedesk.api.workspace.set_active", workspace=str(ws.id))
    return agent


# --- private notes -----------------------------------------------------------


def test_private_note_created_and_listed(authed, db):
    client, ws = authed
    contact = make_contact(db, ws, "919876500001")
    chat = make_chat(db, ws, contact=contact)

    note = _call(client, "wavedesk.api.messages.add_note",
                 chat=str(chat.id), body="VIP customer — handle with care")
    assert note["is_private"] is True
    assert note["message_type"] == "note"

    msgs = _call(client, "wavedesk.api.messages.list_messages", chat=str(chat.id))
    assert [m for m in msgs["messages"] if m["is_private"]]


def test_private_note_never_enters_send_pipeline(authed, db):
    """A note has no wa_message_id and no outbound status — it was never queued."""
    client, ws = authed
    chat = make_chat(db, ws)
    note = _call(client, "wavedesk.api.messages.add_note",
                 chat=str(chat.id), body="internal only")
    row = db.get(Message, uuid.UUID(note["name"]))
    assert row.wa_message_id is None
    assert row.status is None
    assert row.is_private is True


def test_private_note_does_not_stamp_first_response(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    _call(client, "wavedesk.api.messages.add_note", chat=str(chat.id), body="note")
    db.expire_all()
    assert chat.first_response_at is None


def test_note_requires_body_and_workspace_scope(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    r = client.post("/api/method/wavedesk.api.messages.add_note",
                    json={"chat": str(chat.id), "body": "  "})
    assert r.status_code == 400

    other = make_workspace(db)
    foreign = make_chat(db, other)
    r = client.post("/api/method/wavedesk.api.messages.add_note",
                    json={"chat": str(foreign.id), "body": "x"})
    assert r.status_code == 404


def test_echo_never_adopts_a_private_note(authed, db):
    """A fromMe echo whose body matches a private note must create its own
    Message row — never claim the note as the sent copy (review finding)."""
    from app.pipeline import consumer
    from tests.helpers import baileys_event, make_number

    client, ws = authed
    number = make_number(db, ws)
    wa_chat = "919876500009@s.whatsapp.net"
    r = consumer.get_redis()
    stream = f"wa:events:test:{uuid.uuid4().hex[:8]}"

    # first inbound creates the chat, then the agent writes a note saying "ok"
    r.xadd(stream, {"event": baileys_event(ws.id, number.session_ref, wa_chat, "hi")})
    consumer.process_wa_events(stream=stream, r=r)
    db.expire_all()
    chat = db.execute(
        select(Chat).where(Chat.workspace_id == ws.id, Chat.wa_chat_id == wa_chat)
    ).scalar_one()
    note = _call(client, "wavedesk.api.messages.add_note", chat=str(chat.id), body="ok")

    # a real "ok" typed from the paired phone echoes back
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, wa_chat, "ok",
        wa_message_id="WAMID.ECHO1", from_me=True,
    )})
    consumer.process_wa_events(stream=stream, r=r)
    db.expire_all()

    note_row = db.get(Message, uuid.UUID(note["name"]))
    assert note_row.wa_message_id is None  # the note was NOT adopted
    echo = db.execute(
        select(Message).where(
            Message.workspace_id == ws.id, Message.wa_message_id == "WAMID.ECHO1"
        )
    ).scalar_one()
    assert echo.is_private is False


def test_private_note_not_counted_as_sent_traffic(authed, db):
    """Notes never left the app: anti-ban daily counts and the admin send
    clamp must ignore them (review finding)."""
    from app import antiban
    from tests.helpers import make_number

    client, ws = authed
    number = make_number(db, ws)
    chat = make_chat(db, ws, number=number)
    _call(client, "wavedesk.api.messages.add_note", chat=str(chat.id), body="internal")
    db.expire_all()
    assert antiban.sent_today(db, number.id) == 0


def test_set_priority_and_filter(authed, db):
    client, ws = authed
    urgent = make_chat(db, ws)
    make_chat(db, ws)  # second chat, no priority

    out = _call(client, "wavedesk.api.chats.set_priority",
                chat=str(urgent.id), priority="urgent")
    assert out["priority"] == "urgent"

    rows = _call(client, "wavedesk.api.chats.list_chats", priority="urgent")
    assert rows["total"] == 1
    assert rows["chats"][0]["name"] == str(urgent.id)
    assert rows["chats"][0]["priority"] == "urgent"

    # clearing works
    out = _call(client, "wavedesk.api.chats.set_priority", chat=str(urgent.id))
    assert out["priority"] is None


def test_set_priority_rejects_invalid(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    r = client.post("/api/method/wavedesk.api.chats.set_priority",
                    json={"chat": str(chat.id), "priority": "asap"})
    assert r.status_code == 400
    r = client.post("/api/method/wavedesk.api.chats.list_chats",
                    json={"priority": "asap"})
    assert r.status_code == 400


def test_automation_set_priority_action(authed, db):
    """The new set_priority automation action flips the chat's priority."""
    from app import automation

    _, ws = authed
    chat = make_chat(db, ws)
    from app.models import AutomationRule

    rule = AutomationRule(
        workspace_id=ws.id, rule_name="urgent refunds", trigger="message_received",
        conditions=[{"type": "keyword", "value": "refund"}],
        actions=[{"type": "set_priority", "value": "urgent"}], enabled=True,
    )
    db.add(rule)
    db.commit()
    fired = automation.run_trigger(db, ws.id, "message_received", chat, {"body": "refund pls"})
    db.commit()
    assert fired == 1
    db.expire_all()
    assert chat.priority == "urgent"


# --- macros ------------------------------------------------------------------


def test_macro_crud_and_run(authed, db):
    client, ws = authed
    db.add(Label(workspace_id=ws.id, title="vip"))
    db.commit()
    chat = make_chat(db, ws)

    macro = _call(client, "wavedesk.api.macros.create_macro",
                  macro_name="VIP intake", visibility="global",
                  actions=[
                      {"type": "add_label", "value": "vip"},
                      {"type": "set_priority", "value": "high"},
                      {"type": "set_status", "value": "pending"},
                      {"type": "add_private_note", "value": "flagged by VIP macro"},
                  ])
    assert macro["visibility"] == "global"

    out = _call(client, "wavedesk.api.macros.run_macro",
                macro=macro["name"], chat=str(chat.id))
    assert all(r["ok"] for r in out["results"]), out["results"]
    assert out["run_count"] == 1

    db.expire_all()
    assert chat.priority == "high"
    assert chat.status == "pending"
    labels = _call(client, "wavedesk.api.chats.list_chats", priority="high")
    assert labels["chats"][0]["labels"] and labels["chats"][0]["labels"][0]["title"] == "vip"
    msgs = _call(client, "wavedesk.api.messages.list_messages", chat=str(chat.id))
    assert any(m["is_private"] and "VIP macro" in (m["body"] or "") for m in msgs["messages"])

    listed = _call(client, "wavedesk.api.macros.list_macros")["macros"]
    assert listed[0]["run_count"] == 1

    _call(client, "wavedesk.api.macros.delete_macro", macro=macro["name"])
    assert _call(client, "wavedesk.api.macros.list_macros")["macros"] == []


def test_macro_bad_actions_rejected(authed):
    client, _ = authed
    r = client.post("/api/method/wavedesk.api.macros.create_macro",
                    json={"macro_name": "bad", "actions": [{"type": "rm_rf"}]})
    assert r.status_code == 400
    r = client.post("/api/method/wavedesk.api.macros.create_macro",
                    json={"macro_name": "empty", "actions": []})
    assert r.status_code == 400


def test_agent_macros_forced_personal_and_hidden(authed, db, make_user, client):
    """An Agent's macro is personal even if they ask for global, and the
    owner's personal macros stay invisible to the agent."""
    _, ws = authed
    _call(client, "wavedesk.api.macros.create_macro",
          macro_name="owner personal", visibility="personal",
          actions=[{"type": "set_status", "value": "resolved"}])

    _login_as_agent(client, db, make_user, ws)
    mine = _call(client, "wavedesk.api.macros.create_macro",
                 macro_name="agent tries global", visibility="global",
                 actions=[{"type": "set_status", "value": "resolved"}])
    assert mine["visibility"] == "personal"

    names = [m["macro_name"] for m in _call(client, "wavedesk.api.macros.list_macros")["macros"]]
    assert "owner personal" not in names
    assert "agent tries global" in names


def test_macro_cross_workspace_404(authed, db, client):
    _, ws = authed
    other = make_workspace(db)
    from app.models import Macro

    foreign = Macro(workspace_id=other.id, name="foreign",
                    actions=[{"type": "set_status", "value": "open"}])
    db.add(foreign)
    db.commit()
    chat = make_chat(db, ws)
    r = client.post("/api/method/wavedesk.api.macros.run_macro",
                    json={"macro": str(foreign.id), "chat": str(chat.id)})
    assert r.status_code == 404


# --- contact notes -----------------------------------------------------------


def test_contact_notes_crud(authed, db, client):
    _, ws = authed
    contact = make_contact(db, ws, "919876500002")
    note = _call(client, "wavedesk.api.contacts.add_contact_note",
                 contact=str(contact.id), content="Prefers Hindi. Repeat buyer.")
    notes = _call(client, "wavedesk.api.contacts.list_contact_notes",
                  contact=str(contact.id))["notes"]
    assert notes[0]["content"] == "Prefers Hindi. Repeat buyer."
    assert notes[0]["author_name"]

    _call(client, "wavedesk.api.contacts.delete_contact_note", note=note["name"])
    assert _call(client, "wavedesk.api.contacts.list_contact_notes",
                 contact=str(contact.id))["notes"] == []


def test_contact_note_cross_workspace_404(authed, db, client):
    _, _ = authed
    other = make_workspace(db)
    foreign = make_contact(db, other, "919876500003")
    r = client.post("/api/method/wavedesk.api.contacts.add_contact_note",
                    json={"contact": str(foreign.id), "content": "x"})
    assert r.status_code == 404


def test_agent_cannot_delete_others_note(authed, db, make_user, client):
    _, ws = authed
    contact = make_contact(db, ws, "919876500004")
    note = _call(client, "wavedesk.api.contacts.add_contact_note",
                 contact=str(contact.id), content="owner's note")

    _login_as_agent(client, db, make_user, ws)
    r = client.post("/api/method/wavedesk.api.contacts.delete_contact_note",
                    json={"note": note["name"]})
    assert r.status_code == 403


# --- auto-resolve idle chats -------------------------------------------------


def test_auto_resolve_idle_chats(authed, db):
    from app import inbox

    _, ws = authed
    settings = dict(ws.settings or {})
    settings["auto_resolve_days"] = 7
    ws.settings = settings
    db.commit()

    stale = make_chat(db, ws, last_message_at=datetime.now(UTC) - timedelta(days=10))
    fresh = make_chat(db, ws, last_message_at=datetime.now(UTC) - timedelta(days=2))
    pending = make_chat(db, ws, status="pending",
                        last_message_at=datetime.now(UTC) - timedelta(days=30))

    n = inbox.auto_resolve_idle(db)
    db.commit()
    assert n >= 1  # other test workspaces may also qualify — ours must
    db.expire_all()
    assert stale.status == "resolved" and stale.resolved_at is not None
    assert fresh.status == "open"
    assert pending.status == "pending"  # only open chats auto-resolve


def test_auto_resolve_disabled_by_default(authed, db):
    from app import inbox

    _, ws = authed
    make_chat(db, ws, last_message_at=datetime.now(UTC) - timedelta(days=100))
    assert inbox.auto_resolve_idle(db) == 0


def test_auto_resolve_setting_roundtrip(authed, client):
    out = _call(client, "wavedesk.api.workspace.update_workspace_settings",
                auto_resolve_days=14)
    assert out["auto_resolve_days"] == 14
    r = client.post("/api/method/wavedesk.api.workspace.update_workspace_settings",
                    json={"auto_resolve_days": 4000})
    assert r.status_code == 400
