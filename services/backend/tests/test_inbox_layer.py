"""R2 acceptance — assignment/status, teams, labels, canned, masking,
needs-reply, settings, invites."""

from datetime import UTC, datetime, timedelta

import pytest

from app import inbox
from tests.helpers import make_chat, make_contact, make_number


@pytest.fixture
def authed(client, login, db):
    login()
    r = client.post(
        "/api/method/wavedesk.api.onboarding.create_workspace",
        json={"workspace_name": "R2 WS"},
    )
    import uuid

    from app.models import Workspace

    ws = db.get(Workspace, uuid.UUID(r.json()["message"]["workspace"]))
    return client, ws


def _call(client, dotted, expect=200, **params):
    r = client.post(f"/api/method/{dotted}", json=params)
    assert r.status_code == expect, r.text
    return r.json()["message"] if expect == 200 else r.json()


# --- status + assignment ------------------------------------------------------


def test_status_transitions_stamp_resolved_at(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    out = _call(client, "wavedesk.api.assign.set_chat_status",
                chat=str(chat.id), status="resolved")
    assert out["status"] == "resolved"
    db.refresh(chat)
    assert chat.resolved_at is not None
    _call(client, "wavedesk.api.assign.set_chat_status", chat=str(chat.id), status="open")
    db.refresh(chat)
    assert chat.resolved_at is None


def test_snooze_requires_until_and_unsnoozes(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    _call(client, "wavedesk.api.assign.set_chat_status",
          chat=str(chat.id), status="snoozed", expect=400)  # no snoozed_until
    until = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    _call(client, "wavedesk.api.assign.set_chat_status",
          chat=str(chat.id), status="snoozed", snoozed_until=until)
    db.expire_all()  # the API wrote via its own session
    assert inbox.unsnooze_due(db) == 1
    db.refresh(chat)
    assert chat.status == "open"


def test_assign_chat_to_member_and_team(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    me = _call(client, "wavedesk.api.assign.list_members")[0]
    team = _call(client, "wavedesk.api.teams.create_team",
                 team_name="Support", members=[me["user"]])
    out = _call(client, "wavedesk.api.assign.assign_chat",
                chat=str(chat.id), agent=me["user"], team=team["name"])
    assert out["assigned_agent"] == me["user"]
    assert out["assigned_team"] == team["name"]
    # Mine view sees it
    mine = _call(client, "wavedesk.api.chats.list_chats", assignee="me")
    assert mine["total"] == 1


def test_assign_rejects_non_member(authed, db, make_user):
    client, ws = authed
    chat = make_chat(db, ws)
    outsider = make_user()
    _call(client, "wavedesk.api.assign.assign_chat",
          chat=str(chat.id), agent=str(outsider.id), expect=400)


# --- labels + canned -----------------------------------------------------------


def test_labels_crud_and_chat_chips(authed, db):
    client, ws = authed
    chat = make_chat(db, ws)
    label = _call(client, "wavedesk.api.labels.create_label", title="VIP Buyer!")
    assert label["title"] == "vip-buyer"  # slugged
    _call(client, "wavedesk.api.labels.set_chat_labels",
          chat=str(chat.id), labels=[label["name"]])
    rows = _call(client, "wavedesk.api.chats.list_chats")
    assert rows["chats"][0]["labels"][0]["title"] == "vip-buyer"
    # filter by label
    assert _call(client, "wavedesk.api.chats.list_chats", label=label["name"])["total"] == 1
    _call(client, "wavedesk.api.labels.delete_label", label=label["name"])
    assert _call(client, "wavedesk.api.chats.list_chats")["chats"][0]["labels"] == []


def test_canned_ranked_search(authed):
    client, _ = authed
    _call(client, "wavedesk.api.canned.create_canned",
          shortcode="greet", content="Namaste! How can we help?")
    _call(client, "wavedesk.api.canned.create_canned",
          shortcode="regret", content="Sorry, that is out of stock.")
    _call(client, "wavedesk.api.canned.create_canned",
          shortcode="hours", content="We are open 9-6. greet you soon!")
    # 'gre': prefix hit (greet) > shortcode substring (regret) > content (hours)
    out = _call(client, "wavedesk.api.canned.search_canned", term="gre")
    assert [c["shortcode"] for c in out] == ["greet", "regret", "hours"]


# --- masking + settings ---------------------------------------------------------


def test_masking_hides_numbers_from_agents(authed, db, make_user, client):
    _, ws = authed
    contact = make_contact(db, ws, "919876541234", full_name="+91 98765 41234")
    make_chat(db, ws, contact=contact, wa_chat_id="919876541234@s.whatsapp.net")
    _call(client, "wavedesk.api.workspace.update_workspace_settings", mask_numbers=True)

    # owner still sees the raw number
    row = _call(client, "wavedesk.api.chats.list_chats")["chats"][0]
    assert row["contact_phone"] == "919876541234"

    # an Agent member sees the masked number
    from app.models import WorkspaceMember

    agent = make_user()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=agent.id, role="Agent"))
    db.commit()
    client.cookies.clear()
    r = client.post("/api/method/login", json={"usr": agent.email, "pwd": "s3cret-pass"})
    assert r.status_code == 200
    _call(client, "wavedesk.api.workspace.set_active", workspace=str(ws.id))
    row = _call(client, "wavedesk.api.chats.list_chats")["chats"][0]
    assert row["contact_phone"] == "91••••••1234"
    assert row["contact_name"] == "91••••••1234"  # number-as-name masked too
    # and an Agent cannot flip the setting off
    _call(client, "wavedesk.api.workspace.update_workspace_settings",
          mask_numbers=False, expect=403)


# --- needs reply -----------------------------------------------------------------


def test_needs_reply_queue(authed, db):
    client, ws = authed
    number = make_number(db, ws)
    chat = make_chat(db, ws, number=number, chat_type="group",
                     wa_chat_id="g123@g.us")
    assert inbox.looks_like_query("bhai stock available hai kya?")
    inbox.flag_pending_query(chat, "bhai stock available hai kya?")
    chat.pending_query_since = datetime.now(UTC) - timedelta(minutes=15)  # age it
    db.commit()
    out = _call(client, "wavedesk.api.chats.list_chats", needs_reply=True)
    assert out["total"] == 1
    assert out["chats"][0]["needs_reply"] is True
    # a team reply clears the clock (send pipeline stamp)
    from app import gateway
    from app.pipeline import sender

    original = gateway.send_session_message
    gateway.send_session_message = lambda *a: {"wa_message_id": "W-NR"}
    try:
        sender.queue_send(db, chat, "haan, stock hai!", None)
    finally:
        gateway.send_session_message = original
    assert _call(client, "wavedesk.api.chats.list_chats", needs_reply=True)["total"] == 0


# --- invites ----------------------------------------------------------------------


def test_invite_accept_creates_member_and_logs_in(authed, client):
    _, ws = authed
    invite = _call(client, "wavedesk.api.invites.invite_member",
                   email="riya.new@wavedesk.test", role="Agent")
    assert invite["status"] == "pending"

    client.cookies.clear()  # guest accepts
    out = _call(client, "wavedesk.api.invites.accept_invite",
                token=invite["token"], full_name="Riya", password="riya-pass-123")
    assert out["role"] == "Agent"
    # auto-logged-in and workspace-active
    who = _call(client, "frappe.auth.get_logged_user")
    assert who == "riya.new@wavedesk.test"
    active = _call(client, "wavedesk.api.workspace.get_active")
    assert active["workspace"] == str(ws.id)
    assert active["role"] == "Agent"
    # single-use
    client.cookies.clear()
    _call(client, "wavedesk.api.invites.accept_invite",
          token=invite["token"], password="riya-pass-123", expect=400)


def test_invite_existing_user_requires_self_auth(authed, client, make_user):
    """A token for an already-existing account must NOT auto-log-in — managers
    can read invite tokens, so auto-login would be account takeover."""
    _, ws = authed
    victim = make_user()  # an existing WaveDesk user
    invite = _call(client, "wavedesk.api.invites.invite_member",
                   email=victim.email, role="Agent")

    # Guest holding the token cannot become the existing user.
    client.cookies.clear()
    _call(client, "wavedesk.api.invites.accept_invite",
          token=invite["token"], expect=401)

    # The existing user, signed in as themselves, can accept (membership added).
    r = client.post("/api/method/login", json={"usr": victim.email, "pwd": "s3cret-pass"})
    assert r.status_code == 200, r.text
    out = _call(client, "wavedesk.api.invites.accept_invite", token=invite["token"])
    assert out["role"] == "Agent"
    assert _call(client, "frappe.auth.get_logged_user") == victim.email


def test_revoked_invite_rejected(authed, client):
    _, _ = authed
    invite = _call(client, "wavedesk.api.invites.invite_member",
                   email="gone@wavedesk.test")
    _call(client, "wavedesk.api.invites.revoke_invite", invite=invite["name"])
    client.cookies.clear()
    _call(client, "wavedesk.api.invites.accept_invite",
          token=invite["token"], password="whatever-123", expect=400)
