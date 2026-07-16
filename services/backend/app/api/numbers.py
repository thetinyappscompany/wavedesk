"""Numbers API — connect/list/status/disconnect/reconnect/delete, both
transports. Same dotted paths + shapes the SPA already calls."""

import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import select, update

from app import gateway
from app.compat import Ctx, method
from app.models import Chat, WhatsAppNumber
from app.tenancy import active_workspace, require_manager


def _get_checked(ctx: Ctx, number: str) -> WhatsAppNumber:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(WhatsAppNumber, uuid.UUID(number))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Number not found in this workspace")
    return row


def _serialize(row: WhatsAppNumber) -> dict:
    return {
        "name": str(row.id),
        "display_name": row.display_name,
        "connection_type": row.connection_type,
        "status": row.status,
        "phone": row.phone,
        "session_ref": row.session_ref,
        "creation": row.created_at.isoformat() if row.created_at else None,
    }


@method("wavedesk.api.numbers.list_numbers")
def list_numbers(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(WhatsAppNumber)
        .where(WhatsAppNumber.workspace_id == ws.id)
        .order_by(WhatsAppNumber.created_at.desc())
    ).scalars()
    return [_serialize(r) for r in rows]


@method("wavedesk.api.numbers.connect_baileys")
def connect_baileys(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    session_ref = secrets.token_hex(8)
    row = WhatsAppNumber(
        workspace_id=ws.id,
        display_name=ctx.params.get("display_name") or None,
        connection_type="baileys",
        status="connecting",
        session_ref=session_ref,
    )
    ctx.db.add(row)
    ctx.db.flush()
    gateway.create_session(session_ref, str(ws.id))
    return {"number": str(row.id), "session_ref": session_ref}


@method("wavedesk.api.numbers.connect_cloud_number")
def connect_cloud_number(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    for key in ("phone", "phone_number_id", "waba_id", "token"):
        if not ctx.params.get(key):
            raise HTTPException(400, f"{key} is required")
    row = WhatsAppNumber(
        workspace_id=ws.id,
        display_name=ctx.params.get("display_name") or None,
        connection_type="cloud_api",
        status="connected",
        phone=ctx.params["phone"],
        phone_number_id=ctx.params["phone_number_id"],
        waba_id=ctx.params["waba_id"],
    )
    ctx.db.add(row)
    ctx.db.flush()
    return {"number": str(row.id), "status": "connected"}


@method("wavedesk.api.numbers.number_status")
def number_status(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("number") or "")
    if row.connection_type != "baileys":
        return {"status": row.status, "phone": row.phone, "qr": None}
    info = gateway.session_status(row.session_ref)
    status = info.get("status") or row.status
    phone = (info.get("phone") or "").split("@")[0].split(":")[0] or row.phone
    if status != row.status or phone != row.phone:
        row.status = status
        row.phone = phone
    return {"status": status, "phone": phone, "qr": info.get("qr")}


@method("wavedesk.api.numbers.disconnect_number")
def disconnect_number(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("number") or "")
    require_manager(ctx, row.workspace_id)
    gateway.disconnect_session(row.session_ref)
    row.status = "disconnected"
    return {"status": "disconnected"}


@method("wavedesk.api.numbers.reconnect_number")
def reconnect_number(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("number") or "")
    require_manager(ctx, row.workspace_id)
    gateway.reconnect_session(row.session_ref)
    row.status = "connecting"
    return {"status": "connecting"}


@method("wavedesk.api.numbers.delete_number")
def delete_number(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("number") or "")
    require_manager(ctx, row.workspace_id)
    if row.session_ref:
        try:
            gateway.delete_session(row.session_ref)
        except gateway.GatewayError:
            pass  # gateway may already have dropped it
    # unlink chats first (the old LinkExistsError fix, ported)
    ctx.db.execute(update(Chat).where(Chat.number_id == row.id).values(number_id=None))
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}
