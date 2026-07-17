"""Groups API — registry page, detail drawer, audited actions, bulk send."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select

from app import gateway, masking, tasks
from app.compat import Ctx, method
from app.models import Chat, Contact, Group, WhatsAppNumber
from app.pipeline.group_sync import active_members
from app.tenancy import active_workspace, require_manager

PAGE_SIZE_MAX = 100


def _get_checked(ctx: Ctx, group: str) -> Group:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(Group, uuid.UUID(group))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Group not found in this workspace")
    return row


def _session_ref(ctx: Ctx, group: Group) -> str:
    number = ctx.db.get(WhatsAppNumber, group.number_id) if group.number_id else None
    if number is None or number.connection_type != "baileys" or not number.session_ref:
        raise HTTPException(400, "This group has no connected Baileys number")
    return number.session_ref


@method("wavedesk.api.groups.list_groups")
def list_groups(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    limit = min(int(ctx.params.get("limit") or 50), PAGE_SIZE_MAX)
    offset = max(int(ctx.params.get("offset") or 0), 0)
    query = (
        select(Group, Chat)
        .join(Chat, Chat.group_id == Group.id, isouter=True)
        .where(Group.workspace_id == ws.id)
    )
    if ctx.params.get("search"):
        needle = f"%{ctx.params['search'].lower()}%"
        query = query.where(
            func.lower(func.coalesce(Group.subject, "")).like(needle)
            | func.lower(Group.wa_group_id).like(needle)
        )
    total = ctx.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = ctx.db.execute(
        query.order_by(Chat.last_message_at.desc().nulls_last(), Group.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    groups = []
    for group, chat in rows:
        groups.append({
            "name": str(group.id),
            "wa_group_id": group.wa_group_id,
            "subject": group.subject,
            "member_count": group.member_count,
            "invite_link": group.invite_link,
            "owned_by_us": bool(group.owned_by_us),
            "number": str(group.number_id) if group.number_id else None,
            "chat": str(chat.id) if chat else None,
            "unread_count": chat.unread_count if chat else 0,
            "last_message_at": (
                chat.last_message_at.isoformat() if chat and chat.last_message_at else None
            ),
            "needs_reply": bool(chat and chat.pending_query_since),
        })
    return {"groups": groups, "total": total}


@method("wavedesk.api.groups.get_group")
def get_group(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    group = _get_checked(ctx, ctx.params.get("group") or "")
    masked = masking.should_mask(ctx, ws)
    members = []
    for m in active_members(ctx.db, group):
        digits = m.participant_id.split("@")[0].split(":")[0]
        contact_name = None
        if m.contact_id:
            contact = ctx.db.get(Contact, m.contact_id)
            contact_name = contact.full_name if contact else None
            if masked:
                contact_name = masking.mask_name(contact_name, digits)
        members.append({
            "name": str(m.id),
            "display": masking.mask_phone(digits) if masked else digits,
            "role": m.role,
            "contact": str(m.contact_id) if m.contact_id else None,
            "contact_name": contact_name,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        })
    return {
        "name": str(group.id),
        "wa_group_id": group.wa_group_id,
        "subject": group.subject,
        "description": group.description,
        "member_count": group.member_count,
        "invite_link": group.invite_link,
        "owned_by_us": bool(group.owned_by_us),
        "number": str(group.number_id) if group.number_id else None,
        "members": members,
    }


@method("wavedesk.api.groups.update_group")
def update_group(ctx: Ctx) -> dict:
    group = _get_checked(ctx, ctx.params.get("group") or "")
    require_manager(ctx, group.workspace_id)
    subject = ctx.params.get("subject")
    description = ctx.params.get("description")
    gateway.group_update_meta(_session_ref(ctx, group), group.wa_group_id, subject, description)
    if subject is not None:
        group.subject = subject
    if description is not None:
        group.description = description
    return {"group": str(group.id), "subject": subject, "description": description}


@method("wavedesk.api.groups.group_participants")
def group_participants(ctx: Ctx) -> dict:
    group = _get_checked(ctx, ctx.params.get("group") or "")
    require_manager(ctx, group.workspace_id)
    action = ctx.params.get("action") or ""
    if action not in ("add", "remove", "promote", "demote"):
        raise HTTPException(400, f"Invalid action: {action}")
    participants = ctx.params.get("participants") or []
    jids = [
        p if "@" in p else f"{''.join(ch for ch in p if ch.isdigit())}@s.whatsapp.net"
        for p in participants
    ]
    gateway.group_participants_update(_session_ref(ctx, group), group.wa_group_id, jids, action)
    return {"group": str(group.id), "action": action, "count": len(jids)}


@method("wavedesk.api.groups.revoke_group_invite")
def revoke_group_invite(ctx: Ctx) -> dict:
    group = _get_checked(ctx, ctx.params.get("group") or "")
    require_manager(ctx, group.workspace_id)
    result = gateway.group_revoke_invite(_session_ref(ctx, group), group.wa_group_id)
    link = result.get("invite_link") or result.get("code")
    if link and not str(link).startswith("http"):
        link = f"https://chat.whatsapp.com/{link}"
    group.invite_link = link
    return {"group": str(group.id), "invite_link": link}


@method("wavedesk.api.groups.send_to_groups")
def send_to_groups(ctx: Ctx) -> dict:
    """Bulk message N groups — queued through the protected pipeline with
    randomized gaps (the RQ job sleeps; skipped inline in tests)."""
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    body = (ctx.params.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Message body is required")
    group_ids = ctx.params.get("groups") or []
    targets = []
    for gid in group_ids:
        group = _get_checked(ctx, gid)
        targets.append(str(group.id))
    tasks.enqueue(
        run_bulk_send, queue="long",
        workspace_id=str(ws.id), group_ids=targets, body=body,
        agent_user_id=ctx.user_id,
    )
    return {"queued": len(targets)}


def run_bulk_send(workspace_id: str, group_ids: list, body: str, agent_user_id: str | None) -> int:
    """RQ long job: ensure each group chat exists, then queue each send with a
    3–8s randomized gap (anti-ban); per-target failures are skipped."""
    import os
    import random
    import time

    from app.db import get_sessionmaker
    from app.pipeline import sender

    db = get_sessionmaker()()
    sent = 0
    try:
        for i, gid in enumerate(group_ids):
            group = db.get(Group, uuid.UUID(gid))
            if group is None:
                continue
            chat = db.execute(
                select(Chat).where(
                    Chat.workspace_id == group.workspace_id,
                    Chat.wa_chat_id == group.wa_group_id,
                )
            ).scalar_one_or_none()
            if chat is None:
                chat = Chat(
                    workspace_id=group.workspace_id, chat_type="group",
                    wa_chat_id=group.wa_group_id, group_id=group.id,
                    number_id=group.number_id,
                )
                db.add(chat)
                db.flush()
            if i and os.environ.get("WD_TASK_INLINE") != "1":
                time.sleep(random.uniform(3, 8))
            try:
                sender.queue_send(db, chat, body, agent_user_id)
                sent += 1
            except sender.SendError:
                continue  # unlinked number etc. — skip this target
        db.commit()
        return sent
    finally:
        db.close()
