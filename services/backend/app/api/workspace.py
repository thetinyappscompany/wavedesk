"""Workspace onboarding + membership handlers (R0 slice of the old
wavedesk.api.onboarding / wavedesk.api.workspace surface)."""

import uuid

from fastapi import HTTPException

from app import sessions
from app.compat import Ctx, method
from app.models import Workspace, WorkspaceMember
from app.tenancy import active_workspace, get_role


@method("wavedesk.api.onboarding.create_workspace")
def create_workspace(ctx: Ctx) -> dict:
    name = (ctx.params.get("workspace_name") or "").strip()
    if not name:
        raise HTTPException(400, "workspace_name is required")
    ws = Workspace(name=name)
    ctx.db.add(ws)
    ctx.db.flush()
    ctx.db.add(
        WorkspaceMember(workspace_id=ws.id, user_id=uuid.UUID(ctx.user_id), role="Owner")
    )
    sessions.update(ctx.sid, active_workspace=str(ws.id))
    return {"workspace": str(ws.id), "workspace_name": ws.name, "role": "Owner"}


@method("wavedesk.api.workspace.get_active")
def get_active(ctx: Ctx) -> dict:
    ws = active_workspace(ctx)
    return {
        "workspace": str(ws.id),
        "workspace_name": ws.name,
        "plan": ws.plan,
        "role": get_role(ctx, ws.id),
    }


@method("wavedesk.api.workspace.set_active")
def set_active(ctx: Ctx) -> dict:
    ws_id = ctx.params.get("workspace") or ""
    if get_role(ctx, ws_id) is None:
        raise HTTPException(403, "Not a member of that workspace")
    sessions.update(ctx.sid, active_workspace=ws_id)
    return {"workspace": ws_id}
