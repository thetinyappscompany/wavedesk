"""Shared builders for R1+ tests — direct model rows, committed so the
request-scoped sessions inside the compat dispatcher can see them."""

import json
import uuid

from app.models import Chat, Contact, Message, WhatsAppNumber, Workspace


def make_workspace(db, name: str | None = None) -> Workspace:
    ws = Workspace(name=name or f"WS {uuid.uuid4().hex[:6]}")
    db.add(ws)
    db.commit()
    return ws


def make_number(db, ws, **kw) -> WhatsAppNumber:
    row = WhatsAppNumber(
        workspace_id=ws.id,
        connection_type=kw.pop("connection_type", "baileys"),
        status=kw.pop("status", "connected"),
        session_ref=kw.pop("session_ref", f"sess-{uuid.uuid4().hex[:8]}"),
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def make_contact(db, ws, phone: str, **kw) -> Contact:
    row = Contact(workspace_id=ws.id, phone=phone, **kw)
    db.add(row)
    db.commit()
    return row


def make_chat(db, ws, number=None, contact=None, **kw) -> Chat:
    row = Chat(
        workspace_id=ws.id,
        chat_type=kw.pop("chat_type", "dm"),
        wa_chat_id=kw.pop("wa_chat_id", f"{uuid.uuid4().hex[:10]}@s.whatsapp.net"),
        number_id=number.id if number else None,
        contact_id=contact.id if contact else None,
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def make_message(db, ws, chat, **kw) -> Message:
    row = Message(
        workspace_id=ws.id,
        chat_id=chat.id,
        direction=kw.pop("direction", "in"),
        message_type=kw.pop("message_type", "text"),
        body=kw.pop("body", "hello"),
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def baileys_event(workspace_id, session_id: str, wa_chat_id: str, text: str,
                  wa_message_id: str | None = None, from_me: bool = False,
                  push_name: str | None = None) -> str:
    return json.dumps({
        "type": "message.received",
        "transport": "baileys",
        "workspace_hint": str(workspace_id),
        "wa_chat_id": wa_chat_id,
        "wa_message_id": wa_message_id or f"WAMID.{uuid.uuid4().hex[:12]}",
        "payload": {
            "session_id": session_id,
            "message": {
                "key": {"fromMe": from_me},
                "pushName": push_name,
                "message": {"conversation": text},
            },
        },
    })
