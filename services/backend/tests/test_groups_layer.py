"""R3 acceptance — groups registry/actions, monitoring, tickets, analytics."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import gateway
from app.models import Alert, Group, GroupMember, Message, MonitoringRule
from app.pipeline import consumer
from tests.helpers import baileys_event, make_chat, make_contact, make_message, make_number, make_workspace


@pytest.fixture
def authed(client, login, db):
    login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "R3 WS"},
    )
    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws


def _call(client, dotted, expect=200, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


def group_event(ws, session_id, wa_group_id, subject, participants, etype="group.upsert",
                action=None):
    payload = {"id": wa_group_id, "subject": subject, "session_id": session_id,
               "participants": participants}
    if action:
        payload["action"] = action
    return json.dumps({
        "type": etype, "workspace_hint": str(ws.id), "payload": payload,
    })


def _drain(r, stream):
    return consumer.process_wa_events(stream=stream, r=r)


@pytest.fixture
def stream():
    return f"wa:events:test:{uuid.uuid4().hex[:8]}"


@pytest.fixture
def r():
    return consumer.get_redis()


# --- group sync ---------------------------------------------------------------


def test_group_upsert_builds_registry(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    existing = make_contact(db, ws, "919111100001")  # only this one links
    r.xadd(stream, {"event": group_event(
        ws, number.session_ref, "g-reg@g.us", "Traders",
        [{"id": "919111100001@s.whatsapp.net", "admin": True},
         {"id": "919111100002@s.whatsapp.net"}],
    )})
    _drain(r, stream)
    group = db.execute(select(Group).where(Group.workspace_id == ws.id)).scalar_one()
    assert group.subject == "Traders"
    assert group.member_count == 2
    assert group.number_id == number.id
    members = {m.participant_id: m for m in db.execute(
        select(GroupMember).where(GroupMember.group_id == group.id)
    ).scalars()}
    assert members["919111100001@s.whatsapp.net"].role == "admin"
    assert members["919111100001@s.whatsapp.net"].contact_id == existing.id
    assert members["919111100002@s.whatsapp.net"].contact_id is None  # never auto-created


def test_participant_remove_sets_left_and_alerts(db, r, stream):
    ws = make_workspace(db)
    number = make_number(db, ws)
    r.xadd(stream, {"event": group_event(
        ws, number.session_ref, "g-mem@g.us", "Fans",
        [{"id": "919111100003@s.whatsapp.net"}, {"id": "919111100004@s.whatsapp.net"}],
    )})
    _drain(r, stream)
    group = db.execute(select(Group).where(Group.workspace_id == ws.id)).scalar_one()
    db.add(MonitoringRule(workspace_id=ws.id, rule_name="churn watch",
                          rule_type="member_change"))
    db.commit()
    r.xadd(stream, {"event": group_event(
        ws, number.session_ref, "g-mem@g.us", None,
        ["919111100004@s.whatsapp.net"], etype="group.participants", action="remove",
    )})
    _drain(r, stream)
    db.expire_all()
    assert group.member_count == 1
    alert = db.execute(select(Alert).where(Alert.workspace_id == ws.id)).scalar_one()
    assert alert.kind == "member_change"


# --- monitoring on inbound ------------------------------------------------------


def test_keyword_rule_flags_message_and_alerts(authed, db, r, stream):
    client, ws = authed
    number = make_number(db, ws)
    rule = _call(client, "wavedesk.api.monitoring.create_rule",
                 rule_name="Scam watch", rule_type="keyword", keyword="scam")
    assert rule["enabled"] is True
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "g-mon@g.us", "this looks like a SCAM alert"
    )})
    _drain(r, stream)
    msg = db.execute(select(Message).where(Message.workspace_id == ws.id)).scalar_one()
    assert msg.flagged is True
    assert "Scam watch" in msg.flag_reason
    feed = _call(client, "wavedesk.api.monitoring.list_alerts")
    assert feed["unseen"] == 1
    assert feed["alerts"][0]["kind"] == "keyword"
    _call(client, "wavedesk.api.monitoring.mark_alerts_seen")
    assert _call(client, "wavedesk.api.monitoring.list_alerts")["unseen"] == 0


# --- groups API ------------------------------------------------------------------


def test_groups_api_list_get_and_actions(authed, db, r, stream):
    client, ws = authed
    number = make_number(db, ws)
    r.xadd(stream, {"event": group_event(
        ws, number.session_ref, "g-api@g.us", "Wholesale",
        [{"id": "919111100005@s.whatsapp.net", "admin": True}],
    )})
    _drain(r, stream)
    rows = _call(client, "wavedesk.api.groups.list_groups")
    assert rows["total"] == 1
    gid = rows["groups"][0]["name"]
    detail = _call(client, "wavedesk.api.groups.get_group", group=gid)
    assert detail["subject"] == "Wholesale"
    assert detail["members"][0]["display"] == "919111100005"

    calls = {}
    def fake_meta(sid, jid, subject, description):
        calls["meta"] = (sid, jid, subject)
        return {}
    import unittest.mock as mock
    with mock.patch.object(gateway, "group_update_meta", fake_meta):
        _call(client, "wavedesk.api.groups.update_group", group=gid, subject="Wholesale 2.0")
    assert calls["meta"][2] == "Wholesale 2.0"
    assert _call(client, "wavedesk.api.groups.get_group", group=gid)["subject"] == "Wholesale 2.0"

    with mock.patch.object(gateway, "group_revoke_invite", lambda s, j: {"code": "AbCd123"}):
        out = _call(client, "wavedesk.api.groups.revoke_group_invite", group=gid)
    assert out["invite_link"] == "https://chat.whatsapp.com/AbCd123"


def test_bulk_send_queues_through_pipeline(authed, db, r, stream, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    for i in range(2):
        r.xadd(stream, {"event": group_event(
            ws, number.session_ref, f"g-bulk{i}@g.us", f"Bulk {i}",
            [{"id": "919111100006@s.whatsapp.net"}],
        )})
    _drain(r, stream)
    groups = _call(client, "wavedesk.api.groups.list_groups")["groups"]
    sent = []
    monkeypatch.setattr(gateway, "send_session_message",
                        lambda sid, to, text: (sent.append(to), {"wa_message_id": f"W{len(sent)}"})[1])
    out = _call(client, "wavedesk.api.groups.send_to_groups",
                groups=[g["name"] for g in groups], body="diwali offer!")
    assert out["queued"] == 2
    assert sorted(sent) == ["g-bulk0@g.us", "g-bulk1@g.us"]


# --- tickets ----------------------------------------------------------------------


def test_tickets_lifecycle(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    msg = make_message(db, ws, chat, body="my refund never arrived, please help")
    t = _call(client, "wavedesk.api.tickets.create_ticket",
              chat=str(chat.id), source_message=str(msg.id))
    assert t["title"].startswith("my refund never arrived")
    assert t["status"] == "open"
    listed = _call(client, "wavedesk.api.tickets.list_tickets", status="open")
    assert len(listed["tickets"]) == 1
    _call(client, "wavedesk.api.tickets.update_ticket",
          ticket=t["name"], status="in_progress", priority="high")
    got = _call(client, "wavedesk.api.tickets.get_ticket", ticket=t["name"])
    assert (got["status"], got["priority"]) == ("in_progress", "high")
    _call(client, "wavedesk.api.tickets.delete_ticket", ticket=t["name"])
    assert _call(client, "wavedesk.api.tickets.list_tickets")["tickets"] == []


# --- analytics ---------------------------------------------------------------------


def test_dashboard_tiles_trend_and_csv(authed, db, client):
    _, ws = authed
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919111100007")
    chat = make_chat(db, ws, number=number, contact=contact)
    chat.first_response_at = chat.created_at + timedelta(minutes=10)
    make_message(db, ws, chat, direction="in", body="hello")
    db.commit()

    data = _call(client, "wavedesk.api.analytics.workspace_dashboard", days=7)
    assert data["live"]["open"] == 1
    assert data["live"]["unassigned"] == 1
    assert sum(row["count"] for row in data["trend"]) == 1
    assert data["first_response"]["avg"] == 10.0

    r = client.post("/api/method/wavedesk.api.analytics.export_dashboard_csv", json={})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "open,1" in r.text


def test_group_analytics_contributors(authed, db, r, stream):
    client, ws = authed
    number = make_number(db, ws)
    r.xadd(stream, {"event": group_event(
        ws, number.session_ref, "g-an@g.us", "Analytics",
        [{"id": "919111100008@s.whatsapp.net"}, {"id": "919111100009@s.whatsapp.net"}],
    )})
    _drain(r, stream)
    for _ in range(3):
        r.xadd(stream, {"event": baileys_event(
            ws.id, number.session_ref, "g-an@g.us", "chatter",
            participant="919111100008@s.whatsapp.net",
        )})
    _drain(r, stream)
    gid = _call(client, "wavedesk.api.groups.list_groups")["groups"][0]["name"]
    out = _call(client, "wavedesk.api.analytics.group_analytics", group=gid, days=7)
    assert out["messages"] == 3
    assert out["inbound"] == 3
    roll = _call(client, "wavedesk.api.analytics.workspace_analytics", days=7)
    assert roll["groups"] == 1
    assert roll["messages"] == 3


def test_chat_list_shows_group_subject(authed, db, r, stream):
    client, ws = authed
    number = make_number(db, ws)
    r.xadd(stream, {"event": group_event(
        ws, number.session_ref, "g-sub@g.us", "Subject Club",
        [{"id": "919111100010@s.whatsapp.net"}],
    )})
    _drain(r, stream)
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "g-sub@g.us", "hello club"
    )})
    _drain(r, stream)
    rows = _call(client, "wavedesk.api.chats.list_chats", search="subject club")
    assert rows["total"] == 1
    assert rows["chats"][0]["group_subject"] == "Subject Club"
