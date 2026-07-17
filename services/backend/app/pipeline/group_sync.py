"""Group registry sync — applies the gateway's group.* events idempotently.

Membership history via left_at set/cleared; contacts are LINKED when they
already exist, never auto-created (P2.1/P2.2 rules)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app import realtime
from app.models import Chat, Contact, Group, GroupMember, WhatsAppNumber, Workspace


def apply_group_event(db, event: dict) -> None:
    workspace = _workspace(db, event.get("workspace_hint"))
    if workspace is None:
        return
    etype = event.get("type")
    payload = event.get("payload") or {}
    if etype in ("group.upsert", "group.update"):
        _upsert_group(db, workspace, payload)
    elif etype == "group.participants":
        _apply_participants(db, workspace, payload)


def _workspace(db, hint: str | None) -> Workspace | None:
    if not hint:
        return None
    try:
        return db.get(Workspace, uuid.UUID(hint))
    except ValueError:
        return None


def _get_group(db, workspace_id, wa_group_id: str) -> Group | None:
    return db.execute(
        select(Group).where(
            Group.workspace_id == workspace_id, Group.wa_group_id == wa_group_id
        )
    ).scalar_one_or_none()


def _normalized(payload: dict) -> dict:
    """Accept the REAL gateway wire shape. The gateway nests the metadata
    (group.upsert → payload.group, group.update → payload.update) and uses
    Baileys field names (desc, invite_code). The R3 tests were written FLAT,
    so every real event resolved id=None and was silently dropped — zero
    groups ever reached the registry in production. The flat shape stays
    accepted (it falls through unchanged)."""
    inner = payload.get("group") or payload.get("update")
    merged = {**payload, **inner} if isinstance(inner, dict) else dict(payload)
    merged.pop("group", None)
    merged.pop("update", None)
    if merged.get("description") is None and merged.get("desc") is not None:
        merged["description"] = merged["desc"]
    if not merged.get("invite_link") and merged.get("invite_code"):
        merged["invite_link"] = f"https://chat.whatsapp.com/{merged['invite_code']}"
    return merged


def _upsert_group(db, workspace, payload: dict) -> Group | None:
    payload = _normalized(payload)
    wa_group_id = payload.get("id") or payload.get("wa_group_id")
    if not wa_group_id:
        return None
    group = _get_group(db, workspace.id, wa_group_id)
    if group is None:
        group = Group(workspace_id=workspace.id, wa_group_id=wa_group_id)
        db.add(group)
        db.flush()
    if payload.get("subject") is not None:
        group.subject = payload["subject"]
    if payload.get("description") is not None:
        group.description = payload["description"]
    if payload.get("invite_link") is not None:
        group.invite_link = payload["invite_link"]
    if payload.get("owned_by_us") is not None:
        group.owned_by_us = bool(payload["owned_by_us"])
    if payload.get("session_id"):
        number = db.execute(
            select(WhatsAppNumber).where(
                WhatsAppNumber.workspace_id == workspace.id,
                WhatsAppNumber.session_ref == payload["session_id"],
            )
        ).scalar_one_or_none()
        if number:
            group.number_id = number.id
    for participant in payload.get("participants") or []:
        _upsert_member(db, workspace.id, group, participant)
    _refresh_member_count(db, group)
    _backlink_chat(db, workspace.id, group)
    realtime.emit_group_updated(str(workspace.id), str(group.id))
    return group


def _apply_participants(db, workspace, payload: dict) -> None:
    wa_group_id = payload.get("id") or payload.get("wa_group_id")
    group = _get_group(db, workspace.id, wa_group_id) if wa_group_id else None
    if group is None:
        return
    action = payload.get("action")
    now = datetime.now(UTC)
    for jid in payload.get("participants") or []:
        jid = jid if isinstance(jid, str) else (jid.get("id") or "")
        member = db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.participant_id == jid
            )
        ).scalar_one_or_none()
        if action == "remove":
            if member and member.left_at is None:
                member.left_at = now
        elif action in ("add", None):
            if member is None:
                _upsert_member(db, workspace.id, group, {"id": jid})
            else:
                member.left_at = None  # re-joined
        elif action in ("promote", "demote") and member:
            member.role = "admin" if action == "promote" else "member"
    _refresh_member_count(db, group)


def _upsert_member(db, workspace_id, group: Group, participant: dict) -> None:
    jid = participant.get("id") or ""
    if not jid:
        return
    member = db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group.id, GroupMember.participant_id == jid
        )
    ).scalar_one_or_none()
    role = "admin" if participant.get("admin") else "member"
    if member is None:
        member = GroupMember(
            group_id=group.id,
            participant_id=jid,
            role=role,
            contact_id=_link_contact(db, workspace_id, jid),
            joined_at=datetime.now(UTC),
        )
        db.add(member)
    else:
        member.role = role
        member.left_at = None


def _link_contact(db, workspace_id, jid: str):
    """Link an EXISTING contact only — group members never auto-create."""
    digits = jid.split("@")[0].split(":")[0]
    if not digits.isdigit():
        return None
    contact = db.execute(
        select(Contact).where(Contact.workspace_id == workspace_id, Contact.phone == digits)
    ).scalar_one_or_none()
    return contact.id if contact else None


def active_members(db, group: Group) -> list[GroupMember]:
    return list(
        db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.left_at.is_(None)
            ).order_by(GroupMember.role, GroupMember.created_at)
        ).scalars()
    )


def _refresh_member_count(db, group: Group) -> None:
    group.member_count = len(active_members(db, group))


def _backlink_chat(db, workspace_id, group: Group) -> None:
    chat = db.execute(
        select(Chat).where(
            Chat.workspace_id == workspace_id, Chat.wa_chat_id == group.wa_group_id
        )
    ).scalar_one_or_none()
    if chat and chat.group_id is None:
        chat.group_id = group.id
