"""Workspace tenancy — role resolution + guards (non-negotiable #1).

Every workspace-scoped handler resolves the caller's role through here;
no query may cross workspaces.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.compat import Ctx
from app.models import Workspace, WorkspaceMember

MANAGER_ROLES = ("Owner", "Admin")


def get_role(ctx: Ctx, workspace_id: str | uuid.UUID) -> str | None:
    if not ctx.user_id:
        return None
    row = ctx.db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == _uuid(workspace_id),
            WorkspaceMember.user_id == _uuid(ctx.user_id),
        )
    ).scalar_one_or_none()
    return row


def active_workspace(ctx: Ctx) -> Workspace:
    """The caller's active workspace; membership re-verified every call."""
    ws_id = (ctx.session or {}).get("active_workspace")
    if not ws_id:
        raise HTTPException(400, "No active workspace")
    role = get_role(ctx, ws_id)
    if role is None:
        raise HTTPException(403, "Not a member of the active workspace")
    ws = ctx.db.get(Workspace, _uuid(ws_id))
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    return ws


def require_manager(ctx: Ctx, workspace_id: str | uuid.UUID) -> str:
    role = get_role(ctx, workspace_id)
    if role not in MANAGER_ROLES:
        raise HTTPException(403, "Only workspace owners/admins may do this")
    return role


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
