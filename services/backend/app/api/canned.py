"""Canned responses — CRUD + the composer's ranked `/` search."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.compat import Ctx, method
from app.models import CannedResponse
from app.tenancy import active_workspace, require_manager


def _get_checked(ctx: Ctx, canned: str) -> CannedResponse:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(CannedResponse, uuid.UUID(canned))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Canned response not found in this workspace")
    return row


def _serialize(row: CannedResponse) -> dict:
    return {"name": str(row.id), "shortcode": row.shortcode, "content": row.content}


@method("wavedesk.api.canned.list_canned")
def list_canned(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(CannedResponse)
        .where(CannedResponse.workspace_id == ws.id)
        .order_by(CannedResponse.shortcode)
    ).scalars()
    return [_serialize(r) for r in rows]


@method("wavedesk.api.canned.search_canned")
def search_canned(ctx: Ctx) -> list[dict]:
    """Ranked: shortcode prefix (1.0) > shortcode substring (0.5) > content (0.2)."""
    ws = active_workspace(ctx)
    term = (ctx.params.get("term") or "").strip().lower()
    rows = ctx.db.execute(
        select(CannedResponse).where(CannedResponse.workspace_id == ws.id)
    ).scalars()
    scored = []
    for row in rows:
        code = row.shortcode.lower()
        if not term:
            scored.append((0.5, row))
        elif code.startswith(term):
            scored.append((1.0, row))
        elif term in code:
            scored.append((0.5, row))
        elif term in row.content.lower():
            scored.append((0.2, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1].shortcode))
    return [_serialize(r) for _, r in scored]


@method("wavedesk.api.canned.create_canned")
def create_canned(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    shortcode = (ctx.params.get("shortcode") or "").strip().lower()
    content = (ctx.params.get("content") or "").strip()
    if not shortcode or not content:
        raise HTTPException(400, "shortcode and content are required")
    row = CannedResponse(workspace_id=ws.id, shortcode=shortcode, content=content)
    ctx.db.add(row)
    ctx.db.flush()
    return _serialize(row)


@method("wavedesk.api.canned.update_canned")
def update_canned(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("canned") or "")
    require_manager(ctx, row.workspace_id)
    if ctx.params.get("shortcode"):
        row.shortcode = ctx.params["shortcode"].strip().lower()
    if ctx.params.get("content"):
        row.content = ctx.params["content"].strip()
    return _serialize(row)


@method("wavedesk.api.canned.delete_canned")
def delete_canned(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("canned") or "")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)
    return {"deleted": name}
