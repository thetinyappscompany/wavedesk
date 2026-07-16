"""Contacts API — list/get/update (CSV import engine lands in R2)."""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.compat import Ctx, method
from app.models import Chat, Contact
from app.tenancy import active_workspace

PAGE_SIZE_MAX = 100


def _get_checked(ctx: Ctx, contact: str) -> Contact:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(Contact, uuid.UUID(contact))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Contact not found in this workspace")
    return row


def _serialize(row: Contact) -> dict:
    return {
        "name": str(row.id),
        "full_name": row.full_name,
        "phone": row.phone,
        "email": row.email,
        "opt_out": bool(row.opt_out),
        "custom_attributes": row.custom_attributes or {},
    }


def _mask_row(ctx: Ctx, ws, data: dict) -> dict:
    from app import masking

    if masking.should_mask(ctx, ws):
        data["full_name"] = masking.mask_name(data["full_name"], data["phone"])
        data["phone"] = masking.mask_phone(data["phone"])
    return data


@method("wavedesk.api.contacts.list_contacts")
def list_contacts(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    limit = min(int(ctx.params.get("limit") or 50), PAGE_SIZE_MAX)
    offset = max(int(ctx.params.get("offset") or 0), 0)
    query = select(Contact).where(Contact.workspace_id == ws.id)
    if ctx.params.get("search"):
        needle = f"%{ctx.params['search'].lower()}%"
        query = query.where(
            or_(
                func.lower(func.coalesce(Contact.full_name, "")).like(needle),
                Contact.phone.like(f"%{ctx.params['search']}%"),
            )
        )
    total = ctx.db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = ctx.db.execute(
        query.order_by(Contact.created_at.desc()).limit(limit).offset(offset)
    ).scalars()
    return {"contacts": [_mask_row(ctx, ws, _serialize(r)) for r in rows], "total": total}


@method("wavedesk.api.contacts.get_contact")
def get_contact(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("contact") or "")
    chats = ctx.db.execute(
        select(Chat).where(Chat.contact_id == row.id).order_by(Chat.last_message_at.desc())
    ).scalars()
    ws = active_workspace(ctx)
    out = _mask_row(ctx, ws, _serialize(row))
    out["chats"] = [
        {
            "name": str(c.id),
            "status": c.status,
            "number": str(c.number_id) if c.number_id else None,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in chats
    ]
    return out


@method("wavedesk.api.contacts.update_contact")
def update_contact(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("contact") or "")
    if "full_name" in ctx.params:
        row.full_name = (ctx.params.get("full_name") or "").strip() or None
    if "email" in ctx.params:
        row.email = (ctx.params.get("email") or "").strip() or None
    attrs = ctx.params.get("custom_attributes")
    if isinstance(attrs, dict):
        row.custom_attributes = attrs
    return _serialize(row)
