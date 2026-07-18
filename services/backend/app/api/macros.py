"""Macros API — CRUD + run (Chatwoot parity).

Visibility: `global` macros are workspace-wide (Owner/Admin manage them);
`personal` macros belong to their creator. Agents always create personal.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select

from app import macros as engine
from app.api.chats import get_chat_checked
from app.compat import Ctx, method
from app.models import Macro, User
from app.models.inbox import MACRO_VISIBILITIES
from app.tenancy import MANAGER_ROLES, active_workspace, get_role


def _serialize(m: Macro) -> dict:
    return {
        "name": str(m.id),
        "macro_name": m.name,
        "visibility": m.visibility,
        "actions": m.actions or [],
        "run_count": m.run_count or 0,
        "created_by": str(m.created_by_id) if m.created_by_id else None,
    }


def _get_checked(ctx: Ctx, macro_id: str) -> Macro:
    ws = active_workspace(ctx)
    try:
        row = ctx.db.get(Macro, uuid.UUID(macro_id))
    except ValueError:
        row = None
    if row is None or row.workspace_id != ws.id:
        raise HTTPException(404, "Macro not found in this workspace")
    return row


def _can_manage(ctx: Ctx, macro: Macro) -> bool:
    if macro.created_by_id and str(macro.created_by_id) == ctx.user_id:
        return True
    return get_role(ctx, macro.workspace_id) in MANAGER_ROLES


@method("wavedesk.api.macros.list_macros")
def list_macros(ctx: Ctx) -> dict:
    """Global macros + own personal ones; managers see everything (so an
    orphaned personal macro — creator deleted, created_by SET NULL — never
    becomes an invisible ghost nobody can delete)."""
    ws = active_workspace(ctx)
    query = select(Macro).where(Macro.workspace_id == ws.id)
    if get_role(ctx, ws.id) not in MANAGER_ROLES:
        query = query.where(
            or_(
                Macro.visibility == "global",
                Macro.created_by_id == uuid.UUID(ctx.user_id),
            )
        )
    rows = ctx.db.execute(query.order_by(Macro.name)).scalars()
    return {"macros": [_serialize(m) for m in rows]}


@method("wavedesk.api.macros.create_macro")
def create_macro(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    name = (ctx.params.get("macro_name") or "").strip()
    if not name:
        raise HTTPException(400, "macro_name is required")
    try:
        actions = engine.validate_actions(ctx.params.get("actions"))
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    visibility = ctx.params.get("visibility") or "personal"
    if visibility not in MACRO_VISIBILITIES:
        raise HTTPException(400, f"Invalid visibility: {visibility}")
    if get_role(ctx, ws.id) not in MANAGER_ROLES:
        visibility = "personal"  # agents never publish workspace-wide macros
    macro = Macro(
        workspace_id=ws.id,
        name=name[:140],
        visibility=visibility,
        actions=actions,
        created_by_id=uuid.UUID(ctx.user_id),
    )
    ctx.db.add(macro)
    ctx.db.flush()
    return _serialize(macro)


@method("wavedesk.api.macros.update_macro")
def update_macro(ctx: Ctx) -> dict:
    macro = _get_checked(ctx, ctx.params.get("macro") or "")
    if not _can_manage(ctx, macro):
        raise HTTPException(403, "Only the macro's creator or a manager may edit it")
    if "macro_name" in ctx.params:
        name = (ctx.params.get("macro_name") or "").strip()
        if not name:
            raise HTTPException(400, "macro_name cannot be empty")
        macro.name = name[:140]
    if "actions" in ctx.params:
        try:
            macro.actions = engine.validate_actions(ctx.params.get("actions"))
        except ValueError as err:
            raise HTTPException(400, str(err)) from err
    if "visibility" in ctx.params:
        visibility = ctx.params.get("visibility") or "personal"
        if visibility not in MACRO_VISIBILITIES:
            raise HTTPException(400, f"Invalid visibility: {visibility}")
        if visibility == "global" and get_role(ctx, macro.workspace_id) not in MANAGER_ROLES:
            raise HTTPException(403, "Only owners/admins may publish global macros")
        macro.visibility = visibility
    return _serialize(macro)


@method("wavedesk.api.macros.delete_macro")
def delete_macro(ctx: Ctx) -> dict:
    macro = _get_checked(ctx, ctx.params.get("macro") or "")
    if not _can_manage(ctx, macro):
        raise HTTPException(403, "Only the macro's creator or a manager may delete it")
    ctx.db.delete(macro)
    return {"deleted": True}


@method("wavedesk.api.macros.run_macro")
def run_macro(ctx: Ctx) -> dict:
    macro = _get_checked(ctx, ctx.params.get("macro") or "")
    # personal macros are runnable by their creator (managers can run any)
    if (
        macro.visibility != "global"
        and str(macro.created_by_id) != ctx.user_id
        and get_role(ctx, macro.workspace_id) not in MANAGER_ROLES
    ):
        raise HTTPException(404, "Macro not found in this workspace")
    chat = get_chat_checked(ctx, ctx.params.get("chat") or "")
    user = ctx.db.get(User, uuid.UUID(ctx.user_id))
    display = (user.first_name or user.email) if user else None
    results = engine.run_macro(ctx.db, macro, chat, ctx.user_id, display)
    return {"results": results, "run_count": macro.run_count}
