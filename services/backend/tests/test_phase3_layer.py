"""R4 acceptance — automation, routing, SLA, broadcasts, schedules, antiban,
segments, templates."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app import antiban, gateway, inbox, routing, schedules, sla
from tests.helpers import baileys_event, make_chat, make_contact, make_number, make_workspace


def test_within_business_hours_reads_frontend_shape(db):
    """The engine must read the frontend contract: timezone + days:{mon:{open,close}}
    + holidays (not the old tz + [open,close] list shape)."""
    ws = make_workspace(db)
    ws.settings = {
        "business_hours": {
            "enabled": True,
            "timezone": "Asia/Kolkata",
            "days": {"mon": {"open": "09:00", "close": "18:00"}},
            "holidays": ["2026-01-26"],
        }
    }
    db.commit()
    # Monday 12:00 IST → inside the window
    monday_noon = datetime(2026, 1, 5, 6, 30, tzinfo=UTC)  # 12:00 IST
    assert routing.within_business_hours(ws, monday_noon) is True
    # Monday 20:00 IST → after close
    assert routing.within_business_hours(ws, datetime(2026, 1, 5, 14, 30, tzinfo=UTC)) is False
    # A holiday (2026-01-26 is a Monday) → closed even during the window
    assert routing.within_business_hours(ws, datetime(2026, 1, 26, 6, 30, tzinfo=UTC)) is False
    # Disabled → always open
    ws.settings = {"business_hours": {"enabled": False}}
    db.commit()
    assert routing.within_business_hours(ws) is True


@pytest.fixture
def authed(client, login, db):
    login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "R4 WS"},
    )
    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws


def _call(client, dotted, expect=200, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


# --- automation -----------------------------------------------------------------


def test_automation_keyword_rule_fires_on_inbound(authed, db):
    from app.pipeline import consumer

    client, ws = authed
    number = make_number(db, ws)
    label = _call(client, "wavedesk.api.labels.create_label", title="refund")
    _call(client, "wavedesk.api.automation.create_rule",
          rule_name="refund router", trigger="message_received",
          conditions=[{"type": "keyword", "value": "refund"}],
          actions=[{"type": "add_label", "value": "refund"},
                   {"type": "set_status", "value": "pending"}])
    r = consumer.get_redis()
    stream = f"wa:events:test:{uuid.uuid4().hex[:8]}"
    r.xadd(stream, {"event": baileys_event(
        ws.id, number.session_ref, "919222200001@s.whatsapp.net",
        "i want a refund please"
    )})
    consumer.process_wa_events(stream=stream, r=r)
    rows = _call(client, "wavedesk.api.chats.list_chats")
    assert rows["chats"][0]["status"] == "pending"
    assert rows["chats"][0]["labels"][0]["title"] == "refund"
    logs = _call(client, "wavedesk.api.automation.list_logs")
    assert logs and logs[0]["outcome"] == "fired"
    rules = _call(client, "wavedesk.api.automation.list_rules")
    assert rules[0]["run_count"] == 1
    assert label["title"] == "refund"


# --- routing --------------------------------------------------------------------


def test_round_robin_routes_to_online_agent(authed, db):
    client, ws = authed
    me = _call(client, "wavedesk.api.assign.list_members")[0]
    team = _call(client, "wavedesk.api.teams.create_team",
                 team_name="Auto", routing="round_robin", members=[me["user"]])
    _call(client, "wavedesk.api.routing.heartbeat")  # I'm online
    chat = make_chat(db, ws)
    out = _call(client, "wavedesk.api.assign.assign_chat",
                chat=str(chat.id), team=team["name"])
    assert out["assigned_agent"] == me["user"]  # auto-routed on team assign
    status = _call(client, "wavedesk.api.routing.team_status")
    assert status[0]["members"][0]["online"] is True


def test_offline_agent_not_routed(authed, db):
    client, ws = authed
    me = _call(client, "wavedesk.api.assign.list_members")[0]
    routing.get_redis().delete(f"wd:online:{me['user']}")  # ensure offline
    team = _call(client, "wavedesk.api.teams.create_team",
                 team_name="Ghost", routing="round_robin", members=[me["user"]])
    chat = make_chat(db, ws)
    out = _call(client, "wavedesk.api.assign.assign_chat",
                chat=str(chat.id), team=team["name"])
    assert out["assigned_agent"] is None  # stays unassigned, never parked offline


# --- SLA ------------------------------------------------------------------------


def test_sla_breach_detection_and_feed(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    policy = _call(client, "wavedesk.api.sla.create_policy",
                   policy_name="Gold", first_response_mins=60)
    _call(client, "wavedesk.api.sla.attach_policy",
          chat=str(chat.id), policy=policy["name"])
    db.expire_all()
    chat.first_response_due = datetime.now(UTC) - timedelta(minutes=5)  # overdue
    db.commit()
    assert sla.check_breaches(db) == 1
    assert sla.check_breaches(db) == 0  # idempotent — never double-alerts
    feed = _call(client, "wavedesk.api.sla.list_breaches")
    assert "first_response" in feed[0]["detail"]


def test_sla_no_breach_when_answered(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    chat.first_response_at = datetime.now(UTC)  # already answered
    chat.first_response_due = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    assert sla.check_breaches(db) == 0


# --- broadcasts -----------------------------------------------------------------


def test_broadcast_csv_dedupe_optout_and_run(authed, db, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    opted = make_contact(db, ws, "919222200011", opt_out=True)
    bc = _call(client, "wavedesk.api.broadcasts.create_broadcast",
               broadcast_name="Promo", number=str(number.id),
               message_template="Hi {{name}}!",
               audience_type="csv",
               audience=[
                   {"phone": "919222200010", "name": "A"},
                   {"phone": "+91 92222-00010", "name": "A dup"},
                   {"phone": "919222200011", "name": "Opted"},  # opted out
                   {"phone": "919222200012", "name": "B"},
               ])
    assert bc["total_recipients"] == 2  # deduped + opt-out skipped
    sent_to = []
    monkeypatch.setattr(gateway, "send_session_message",
                        lambda sid, to, text: (sent_to.append((to, text)),
                                               {"wa_message_id": f"W{len(sent_to)}"})[1])
    out = _call(client, "wavedesk.api.broadcasts.start_broadcast", broadcast=bc["name"])
    assert out["status"] in ("sending", "completed")
    report = _call(client, "wavedesk.api.broadcasts.delivery_report", broadcast=bc["name"])
    assert report["counts"]["sent"] == 2
    assert report["broadcast"]["status"] == "completed"
    assert any("Hi A!" == text for _, text in sent_to)  # {{name}} rendered
    assert opted.opt_out is True


def test_broadcast_failure_auto_pause(authed, db, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    bc = _call(client, "wavedesk.api.broadcasts.create_broadcast",
               broadcast_name="Doomed", number=str(number.id),
               message_template="x", audience_type="csv",
               failure_pause_pct=10,
               audience=[{"phone": f"91922220002{i}"} for i in range(8)])
    monkeypatch.setattr(gateway, "send_session_message",
                        lambda *a: (_ for _ in ()).throw(gateway.GatewayError("down")))
    _call(client, "wavedesk.api.broadcasts.start_broadcast", broadcast=bc["name"])
    report = _call(client, "wavedesk.api.broadcasts.delivery_report", broadcast=bc["name"])
    assert report["broadcast"]["status"] == "paused"  # ban-signal auto-pause
    assert report["counts"]["failed"] >= 5


def test_stop_reply_sets_opt_out(db):
    """STOP through the real consumer flips the contact's opt_out."""
    from app.pipeline import consumer
    from tests.helpers import baileys_event as ev

    ws = make_workspace(db)
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919222200030")
    r = consumer.get_redis()
    stream = f"wa:events:test:{uuid.uuid4().hex[:8]}"
    r.xadd(stream, {"event": ev(ws.id, number.session_ref,
                                "919222200030@s.whatsapp.net", "STOP")})
    consumer.process_wa_events(stream=stream, r=r)
    db.refresh(contact)
    assert contact.opt_out is True


# --- schedules ------------------------------------------------------------------


def test_schedule_once_fires_and_completes(authed, db, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    contact = make_contact(db, ws, "919222200040")
    chat = make_chat(db, ws, number=number, contact=contact,
                     wa_chat_id="919222200040@s.whatsapp.net")
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    sched = _call(client, "wavedesk.api.schedules.create_schedule",
                  title="Reminder", target_type="chat", target=str(chat.id),
                  body="scheduled hello", schedule_type="once", scheduled_at=past)
    assert sched["next_run_at"]
    monkeypatch.setattr(gateway, "send_session_message",
                        lambda *a: {"wa_message_id": "W-SCHED"})
    assert schedules.run_due_schedules() == 1
    rows = _call(client, "wavedesk.api.schedules.list_schedules")
    assert rows[0]["status"] == "sent"
    assert rows[0]["run_count"] == 1
    msgs = _call(client, "wavedesk.api.messages.list_messages", chat=str(chat.id))
    assert msgs["messages"][-1]["body"] == "scheduled hello"


def test_recurring_daily_advances(db):
    from app.models import ScheduledMessage

    ws = make_workspace(db)
    sched = ScheduledMessage(
        workspace_id=ws.id, title="Daily", target_type="chat",
        schedule_type="recurring", recurrence={"frequency": "daily", "time": "09:00"},
    )
    nxt = schedules.compute_next_run(sched)
    assert nxt > datetime.now(UTC)
    after = schedules.compute_next_run(sched, after=nxt)
    assert after.date() >= nxt.date()


# --- antiban --------------------------------------------------------------------


def test_warmup_ramp_and_dispatch_gate(authed, db):
    client, ws = authed
    number = make_number(db, ws)
    _call(client, "wavedesk.api.antiban.start_warmup",
          number=str(number.id), daily_target=1000)
    db.expire_all()
    assert antiban.warmup_cap(number.warmup_started_on, 1000) == 20  # day 1
    assert antiban.can_dispatch(db, number.id) is True  # 0 sent < 20
    health = _call(client, "wavedesk.api.antiban.number_health")
    assert health[0]["warming"] is True
    assert health[0]["daily_cap"] == 20
    out = _call(client, "wavedesk.api.antiban.refresh_health", number=str(number.id))
    assert out["score"] == 100  # no failures yet
    assert out["risk"] == "low"


# --- segments -------------------------------------------------------------------


def test_segment_matching_and_broadcast_audience(authed, db, monkeypatch):
    client, ws = authed
    number = make_number(db, ws)
    make_contact(db, ws, "919222200050", tags="vip, wholesale")
    make_contact(db, ws, "919222200051")  # untagged
    seg = _call(client, "wavedesk.api.segments.create_segment",
                segment_name="VIPs", match_type="all",
                filters=[{"type": "has_tag", "value": "vip"}])
    preview = _call(client, "wavedesk.api.segments.preview_segment", segment=seg["name"])
    assert preview["count"] == 1
    assert preview["sample"][0]["phone"] == "919222200050"
    bc = _call(client, "wavedesk.api.broadcasts.create_broadcast",
               broadcast_name="VIP blast", number=str(number.id),
               message_template="hello", audience_type="segment",
               audience_ref=seg["name"])
    assert bc["total_recipients"] == 1


def test_segment_cross_workspace_rejected(authed, db):
    client, ws = authed
    number = make_number(db, ws)
    other = make_workspace(db)
    from app.models import Segment

    foreign = Segment(workspace_id=other.id, segment_name="Foreign", filters=[])
    db.add(foreign)
    db.commit()
    _call(client, "wavedesk.api.broadcasts.create_broadcast", expect=400,
          broadcast_name="X", number=str(number.id), message_template="x",
          audience_type="segment", audience_ref=str(foreign.id))


# --- templates ------------------------------------------------------------------


def test_template_validation_render_and_local_submit(authed):
    client, _ = authed
    t = _call(client, "wavedesk.api.templates.create_template",
              template_name="Diwali Offer", category="marketing",
              body="Hi {{1}}, get {{2}}% off!")
    assert t["template_name"] == "diwali_offer"
    assert t["variable_count"] == 2
    _call(client, "wavedesk.api.templates.create_template", expect=400,
          template_name="bad", body="Hi {{2}} only")  # non-sequential
    rendered = _call(client, "wavedesk.api.templates.preview_template",
                     template=t["name"], values=["Riya", 20])
    assert rendered["rendered"] == "Hi Riya, get 20% off!"
    out = _call(client, "wavedesk.api.templates.submit_template", template=t["name"])
    assert out["live"] is False  # no Cloud API number → local pending + note
    assert "Meta" in out["note"]
    rows = _call(client, "wavedesk.api.templates.list_templates")
    assert rows[0]["status"] == "pending"


# --- inbox status trigger ----------------------------------------------------------


def test_status_change_trigger(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    _call(client, "wavedesk.api.automation.create_rule",
          rule_name="resolve watch", trigger="status_change",
          conditions=[], actions=[{"type": "add_label", "value": "resolved-once"}])
    _call(client, "wavedesk.api.labels.create_label", title="resolved-once")
    inbox.set_status(db, chat, "resolved")
    db.commit()
    logs = _call(client, "wavedesk.api.automation.list_logs")
    assert any(entry["detail"] == "status_change" for entry in logs)


def test_template_allows_reused_positional_var():
    import uuid as _uuid

    from app import templates_engine
    from app.models import MessageTemplate

    t = MessageTemplate(workspace_id=_uuid.uuid4(), template_name="greet",
                        body="Hi {{1}}, bye {{1}}")
    templates_engine.validate(t)  # reusing {{1}} is valid — must not raise
    assert t.variable_count == 1


def test_recurring_schedule_uses_its_timezone():
    import uuid as _uuid
    from datetime import timezone

    from app import schedules
    from app.models import ScheduledMessage

    sched = ScheduledMessage(
        workspace_id=_uuid.uuid4(), schedule_type="recurring",
        recurrence={"frequency": "daily", "time": "09:00", "timezone": "Asia/Kolkata"},
    )
    nxt = schedules.compute_next_run(sched)
    # 09:00 in Asia/Kolkata (UTC+5:30) is 03:30 UTC
    in_utc = nxt.astimezone(timezone.utc)
    assert in_utc.hour == 3 and in_utc.minute == 30
