"""R1 acceptance — numbers/chats/messages/contacts/send API surface."""

from datetime import UTC, datetime, timedelta

import pytest

from app import gateway
from tests.helpers import make_chat, make_contact, make_message, make_number, make_workspace


@pytest.fixture
def authed(client, login, db):
    """Logged-in client with an active workspace created through the API."""
    login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "Inbox WS"},
    )
    import uuid

    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws


def _call(client, dotted, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == 200, r.text
    return r.json()["message"]


# --- numbers -----------------------------------------------------------------


def test_connect_and_list_numbers(authed, monkeypatch):
    client, _ = authed
    monkeypatch.setattr(gateway, "create_session", lambda sid, ws: {"status": "connecting"})
    out = _call(client, "wavedesk.api.numbers.connect_baileys", display_name="Main")
    assert out["session_ref"]
    rows = _call(client, "wavedesk.api.numbers.list_numbers")
    assert rows[0]["display_name"] == "Main"
    assert rows[0]["status"] == "connecting"


def test_number_status_persists_gateway_state(authed, monkeypatch):
    client, _ = authed
    monkeypatch.setattr(gateway, "create_session", lambda sid, ws: {})
    number = _call(client, "wavedesk.api.numbers.connect_baileys")["number"]
    monkeypatch.setattr(
        gateway, "session_status",
        lambda sid: {"status": "connected", "phone": "919876000001:2@s.whatsapp.net", "qr": None},
    )
    out = _call(client, "wavedesk.api.numbers.number_status", number=number)
    assert out == {"status": "connected", "phone": "919876000001", "qr": None}
    rows = _call(client, "wavedesk.api.numbers.list_numbers")
    assert rows[0]["status"] == "connected"


def test_session_status_flattens_nested_gateway_response(monkeypatch):
    """The gateway nests SessionInfo under `session` ({session, qr, restored});
    session_status must flatten it so number_status reads status/phone/qr."""
    monkeypatch.setattr(
        gateway, "_request",
        lambda method, path, json=None: {
            "session": {"id": "s1", "status": "connected", "phone": "919876000001:1@s.whatsapp.net"},
            "qr": None,
            "restored": True,
        },
    )
    out = gateway.session_status("s1")
    assert out["status"] == "connected"
    assert out["phone"] == "919876000001:1@s.whatsapp.net"
    assert out["qr"] is None


def test_gateway_error_maps_to_502(authed, monkeypatch):
    client, _ = authed
    monkeypatch.setattr(gateway, "create_session", lambda sid, ws: {})
    number = _call(client, "wavedesk.api.numbers.connect_baileys")["number"]

    def _boom(sid):
        raise gateway.GatewayError("gateway unreachable: ConnectError")

    monkeypatch.setattr(gateway, "session_status", _boom)
    r = client.post(
        "/api/method/wavedesk.api.numbers.number_status", json={"number": number}
    )
    assert r.status_code == 502  # not an opaque 500


def test_delete_number_unlinks_chats(authed, db, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    chat = make_chat(db, ws, number=number)
    monkeypatch.setattr(gateway, "delete_session", lambda sid: {})
    _call(client, "wavedesk.api.numbers.delete_number", number=str(number.id))
    db.expire_all()
    assert chat.number_id is None
    assert _call(client, "wavedesk.api.numbers.list_numbers") == []


# --- chats + messages ---------------------------------------------------------


def test_list_chats_filters_and_search(authed, db):
    client, ws = authed
    number = make_number(db, ws)
    asha = make_contact(db, ws, "919000011111", full_name="Asha Traders")
    riya = make_contact(db, ws, "919000022222", full_name="Riya")
    make_chat(db, ws, number=number, contact=asha,
              wa_chat_id="919000011111@s.whatsapp.net", status="open")
    make_chat(db, ws, number=number, contact=riya,
              wa_chat_id="919000022222@s.whatsapp.net", status="resolved")

    out = _call(client, "wavedesk.api.chats.list_chats")
    assert out["total"] == 2
    out = _call(client, "wavedesk.api.chats.list_chats", status="resolved")
    assert out["total"] == 1
    assert out["chats"][0]["contact_name"] == "Riya"
    out = _call(client, "wavedesk.api.chats.list_chats", search="asha")
    assert out["total"] == 1
    assert out["chats"][0]["contact_phone"] == "919000011111"


def test_chats_are_workspace_scoped(authed, db):
    client, _ = authed
    other = make_workspace(db)
    make_chat(db, other, wa_chat_id="919000033333@s.whatsapp.net")
    assert _call(client, "wavedesk.api.chats.list_chats")["total"] == 0


def test_messages_pagination_and_mark_read(authed, db):
    client, ws = authed
    chat = make_chat(db, ws, unread_count=3)
    base = datetime.now(UTC)
    for i in range(3):
        make_message(db, ws, chat, body=f"m{i}", created_at=base + timedelta(seconds=i))

    out = _call(client, "wavedesk.api.messages.list_messages", chat=str(chat.id), limit=2)
    assert [m["body"] for m in out["messages"]] == ["m1", "m2"]
    assert out["next_before"]
    older = _call(
        client, "wavedesk.api.messages.list_messages",
        chat=str(chat.id), limit=2, before=out["next_before"],
    )
    assert [m["body"] for m in older["messages"]] == ["m0"]

    read = _call(client, "wavedesk.api.messages.mark_chat_read", chat=str(chat.id))
    assert read["unread_count"] == 0


def test_foreign_chat_is_404(authed, db):
    client, _ = authed
    other = make_workspace(db)
    foreign = make_chat(db, other)
    r = client.post(
        "/api/method/wavedesk.api.messages.list_messages", json={"chat": str(foreign.id)}
    )
    assert r.status_code == 404


# --- contacts ------------------------------------------------------------------


def test_contacts_list_search_update(authed, db):
    client, ws = authed
    contact = make_contact(db, ws, "919000044444", full_name="Old Name")
    out = _call(client, "wavedesk.api.contacts.list_contacts", search="9000044")
    assert out["total"] == 1
    updated = _call(
        client, "wavedesk.api.contacts.update_contact",
        contact=str(contact.id), full_name="New Name", email="n@x.test",
    )
    assert updated["full_name"] == "New Name"
    profile = _call(client, "wavedesk.api.contacts.get_contact", contact=str(contact.id))
    assert profile["email"] == "n@x.test"


# --- send ----------------------------------------------------------------------


def test_send_message_api_round_trip(authed, db, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919000055555")
    chat = make_chat(db, ws, number=number, contact=contact,
                     wa_chat_id="919000055555@s.whatsapp.net")
    monkeypatch.setattr(
        "app.pipeline.sender.gateway.send_session_message",
        lambda sid, to, text: {"wa_message_id": "WAMID.API1"},
    )
    out = _call(client, "wavedesk.api.send.send_message", chat=str(chat.id), body="hi!")
    assert out["status"] == "queued"
    msgs = _call(client, "wavedesk.api.messages.list_messages", chat=str(chat.id))
    assert msgs["messages"][-1]["status"] == "sent"
    assert msgs["messages"][-1]["direction"] == "out"
