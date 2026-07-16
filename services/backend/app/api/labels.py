"""Labels CRUD + per-chat label list (the picker replaces the whole list)."""

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.models import Chat, ChatLabel, Label
from app.tenancy import active_workspace, require_manager

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _slug(title: str) -> str:
    return _SLUG_RE.sub("-", title.strip().lower()).strip("-")


def _get_checked(ctx: Ctx, label: str) -> Label:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(Label, uuid.UUID(label))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Label not found in this workspace")
    return row


def _serialize(row: Label) -> dict:
    return {
        "name": str(row.id),
        "title": row.title,
        "color": row.color,
        "description": row.description,
    }


@method("wavedesk.api.labels.list_labels")
def list_labels(ctx: Ctx) -> list[dict]:
    ws = active_workspace(ctx)
    rows = ctx.db.execute(
        select(Label).where(Label.workspace_id == ws.id).order_by(Label.title)
    ).scalars()
    return [_serialize(r) for r in rows]


@method("wavedesk.api.labels.create_label")
def create_label(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    require_manager(ctx, ws.id)
    title = _slug(ctx.params.get("title") or "")
    if not title:
        raise HTTPException(400, "title is required")
    row = Label(
        workspace_id=ws.id,
        title=title,
        color=ctx.params.get("color") or "#64748b",
        description=ctx.params.get("description"),
    )
    ctx.db.add(row)
    ctx.db.flush()
    return _serialize(row)


@method("wavedesk.api.labels.update_label")
def update_label(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("label") or "")
    require_manager(ctx, row.workspace_id)
    if ctx.params.get("title"):
        row.title = _slug(ctx.params["title"])
    if ctx.params.get("color"):
        row.color = ctx.params["color"]
    if "description" in ctx.params:
        row.description = ctx.params.get("description")
    return _serialize(row)


@method("wavedesk.api.labels.delete_label")
def delete_label(ctx: Ctx) -> dict:
    row = _get_checked(ctx, ctx.params.get("label") or "")
    require_manager(ctx, row.workspace_id)
    name = str(row.id)
    ctx.db.delete(row)  # chat_labels cascade
    return {"deleted": name}


@method("wavedesk.api.labels.set_chat_labels")
def set_chat_labels(ctx: Ctx) -> dict:
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    wanted = ctx.params.get("labels") or []
    # verify every label belongs to this workspace before replacing
    labels = []
    for lid in wanted:
        row = _get_checked(ctx, lid)
        labels.append(row)
    ctx.db.query(ChatLabel).filter(ChatLabel.chat_id == chat.id).delete()
    for row in labels:
        ctx.db.add(ChatLabel(chat_id=chat.id, label_id=row.id))
    return {
        "chat": str(chat.id),
        "labels": [{"label": str(r.id), "title": r.title, "color": r.color} for r in labels],
    }


def chat_labels_map(db, chat_ids: list) -> dict[str, list[dict]]:
    """{chat_id: [chips]} for the list pane — one query, no N+1."""
    if not chat_ids:
        return {}
    rows = db.execute(
        select(ChatLabel.chat_id, Label)
        .join(Label, ChatLabel.label_id == Label.id)
        .where(ChatLabel.chat_id.in_(chat_ids))
    ).all()
    out: dict[str, list[dict]] = {}
    for chat_id, label in rows:
        out.setdefault(str(chat_id), []).append(
            {"label": str(label.id), "title": label.title, "color": label.color}
        )
    return out


def chats_with_label(db, workspace_id, label_id: str) -> list:
    rows = db.execute(
        select(ChatLabel.chat_id)
        .join(Chat, ChatLabel.chat_id == Chat.id)
        .where(ChatLabel.label_id == uuid.UUID(label_id), Chat.workspace_id == workspace_id)
    ).scalars()
    return list(rows)
