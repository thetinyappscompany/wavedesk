"""R8 — ETL transform + FK-remap + idempotency, verified against real Postgres.

Uses an in-memory Frappe-shaped source (DictSource) so we exercise the mapping
and deterministic-id remapping without needing a second live database; rows are
written into the real target schema via the ETL's own upsert path.
"""

from datetime import datetime, timezone

import pytest

from app.etl.idmap import to_uuid
from app.etl.run import migrate
from app.models import (
    Chat,
    ChatLabel,
    Contact,
    Message,
    Ticket,
    User,
    WalletTransaction,
    WhatsAppNumber,
    Workspace,
    WorkspaceMember,
)

_NOW = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)


class DictSource:
    """Minimal stand-in for PgSource: {table_name: [frappe_row, ...]}."""

    def __init__(self, data: dict[str, list[dict]]):
        self._data = data

    def rows(self, table: str):
        return list(self._data.get(table, []))


def _row(name: str, **fields) -> dict:
    return {"name": name, "creation": _NOW, "modified": _NOW, **fields}


@pytest.fixture
def frappe_data():
    """One coherent workspace graph spanning the FK chain."""
    return DictSource({
        "tabUser": [
            _row("owner@etl-r8.test", first_name="Owner", enabled=1),
            _row("agent@etl-r8.test", first_name="Agent", enabled=1),
        ],
        "tabWD Workspace": [
            _row("WS-R8-1", workspace_name="R8 Co", plan="Trial",
                 settings='{"mask_numbers": true, "needs_reply_minutes": 15}',
                 suspended=0, owner_user="owner@etl-r8.test"),
        ],
        "tabWD Workspace Member": [
            _row("wm-1", parent="WS-R8-1", parenttype="WD Workspace",
                 user="owner@etl-r8.test", role="Owner"),
            _row("wm-2", parent="WS-R8-1", parenttype="WD Workspace",
                 user="agent@etl-r8.test", role="Agent"),
        ],
        "tabWD WhatsApp Number": [
            _row("WNUM-R8-1", workspace="WS-R8-1", phone="919000000001",
                 display_name="Main", connection_type="baileys", status="connected",
                 session_ref="sess-abc", health_score=88, risk_level="low"),
        ],
        "tabWD Contact": [
            _row("CONT-R8-1", workspace="WS-R8-1", phone="919444400001",
                 full_name="Riya", email="riya@x.test", opt_out=0, erased=0,
                 tags="vip,lead", custom_attributes='{"city": "Pune"}'),
        ],
        "tabWD Chat": [
            _row("CHAT-R8-1", workspace="WS-R8-1", chat_type="dm",
                 wa_chat_id="919444400001@s.whatsapp.net", status="open",
                 number="WNUM-R8-1", contact="CONT-R8-1",
                 assigned_agent="agent@etl-r8.test", unread_count=2,
                 last_message_at=_NOW, first_response_breached=0, resolution_breached=0),
        ],
        "tabWD Label": [
            _row("LBL-R8-1", workspace="WS-R8-1", title="urgent", color="#ef4444"),
        ],
        "tabWD Chat Label": [
            _row("cl-1", parent="CHAT-R8-1", parenttype="WD Chat", label="LBL-R8-1"),
        ],
        "tabWD Message": [
            _row("11111111-1111-1111-1111-111111111111", workspace="WS-R8-1",
                 chat="CHAT-R8-1", direction="in", wa_message_id="wamid.AAA",
                 message_type="text", body="hello", sender_contact="CONT-R8-1",
                 flagged=0, is_voice=0, media_size=0, media_duration=0),
            _row("22222222-2222-2222-2222-222222222222", workspace="WS-R8-1",
                 chat="CHAT-R8-1", direction="out", wa_message_id="wamid.BBB",
                 message_type="text", body="hi there", sender_agent="agent@etl-r8.test",
                 status="sent", sent_via="baileys", flagged=0, is_voice=0,
                 media_size=0, media_duration=0),
        ],
        "tabWD Ticket": [
            _row("TKT-R8-1", workspace="WS-R8-1", title="Refund", status="open",
                 priority="high", chat="CHAT-R8-1",
                 source_message="11111111-1111-1111-1111-111111111111",
                 assigned_agent="agent@etl-r8.test"),
        ],
        "tabWD Wallet Transaction": [
            _row("WTX-R8-1", workspace="WS-R8-1", txn_type="topup", amount=500.0,
                 running_balance=500.0, reference="seed", idempotency_key="seed:WS-R8-1"),
            _row("WTX-R8-2", workspace="WS-R8-1", txn_type="deduction", amount=-64.89,
                 running_balance=435.11, reference="ai", idempotency_key="ai:msg-1"),
        ],
    })


def test_full_chain_migrates_with_fk_remap(frappe_data, db):
    counts = migrate(frappe_data, db)
    db.expire_all()

    assert counts["WD Message"] == 2
    ws_id = to_uuid("WD Workspace", "WS-R8-1")

    # workspace + JSON settings survived the Long-Text → JSONB conversion
    ws = db.get(Workspace, ws_id)
    assert ws.name == "R8 Co"
    assert ws.settings["mask_numbers"] is True
    assert ws.settings["needs_reply_minutes"] == 15

    # user carries email; password is the unusable placeholder (can't transfer)
    owner = db.get(User, to_uuid("User", "owner@etl-r8.test"))
    assert owner.email == "owner@etl-r8.test"
    from app.security import verify_password
    assert not verify_password("anything", owner.password_hash)

    # child table → parent FK from Frappe `parent`
    members = db.query(WorkspaceMember).filter_by(workspace_id=ws_id).all()
    assert {m.role for m in members} == {"Owner", "Agent"}
    assert {m.user_id for m in members} == {
        to_uuid("User", "owner@etl-r8.test"), to_uuid("User", "agent@etl-r8.test")}

    # chat's every Link resolved to the deterministic UUID of its referent
    chat = db.get(Chat, to_uuid("WD Chat", "CHAT-R8-1"))
    assert chat.number_id == to_uuid("WD WhatsApp Number", "WNUM-R8-1")
    assert chat.contact_id == to_uuid("WD Contact", "CONT-R8-1")
    assert chat.assigned_agent_id == to_uuid("User", "agent@etl-r8.test")
    assert chat.unread_count == 2

    # contact JSON + bool + tags
    contact = db.get(Contact, to_uuid("WD Contact", "CONT-R8-1"))
    assert contact.custom_attributes == {"city": "Pune"}
    assert contact.opt_out is False
    assert contact.tags == "vip,lead"

    # number scalars
    num = db.get(WhatsAppNumber, to_uuid("WD WhatsApp Number", "WNUM-R8-1"))
    assert num.health_score == 88 and num.risk_level == "low"

    # messages point at the chat; UUID-named message keeps a consistent id
    msgs = db.query(Message).filter_by(chat_id=chat.id).order_by(Message.direction).all()
    assert [m.direction for m in msgs] == ["in", "out"]
    assert msgs[1].sender_agent_id == to_uuid("User", "agent@etl-r8.test")

    # chat_label M2M via parent
    cl = db.query(ChatLabel).filter_by(chat_id=chat.id).one()
    assert cl.label_id == to_uuid("WD Label", "LBL-R8-1")

    # ticket links chat + source message
    tkt = db.get(Ticket, to_uuid("WD Ticket", "TKT-R8-1"))
    assert tkt.chat_id == chat.id
    assert tkt.source_message_id == to_uuid("WD Message", "11111111-1111-1111-1111-111111111111")


def test_wallet_ledger_migrates_append_only(frappe_data, db):
    migrate(frappe_data, db)
    db.expire_all()
    ws_id = to_uuid("WD Workspace", "WS-R8-1")
    txns = db.query(WalletTransaction).filter_by(workspace_id=ws_id).all()
    # both rows, idempotency keys + amounts preserved; running_balance dropped
    assert {t.idempotency_key for t in txns} == {"seed:WS-R8-1", "ai:msg-1"}
    assert round(sum(t.amount for t in txns), 2) == 435.11  # derived balance
    assert not any(hasattr(t, "running_balance") for t in txns)


def test_rerun_is_idempotent(frappe_data, db):
    migrate(frappe_data, db)
    migrate(frappe_data, db)  # second pass must upsert, not duplicate
    db.expire_all()
    ws_id = to_uuid("WD Workspace", "WS-R8-1")
    assert db.query(Message).filter_by(workspace_id=ws_id).count() == 2
    assert db.query(WalletTransaction).filter_by(workspace_id=ws_id).count() == 2
    assert db.query(WorkspaceMember).filter_by(workspace_id=ws_id).count() == 2


def test_empty_source_is_noop(db):
    counts = migrate(DictSource({}), db)
    assert sum(counts.values()) == 0
