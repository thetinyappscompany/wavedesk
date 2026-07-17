"""Platform superadmin (System-Manager equivalent = User.is_platform_admin).
Cross-workspace, NOT tenant-scoped. + assert_can_send enforcement."""

from sqlalchemy import func, select

from app.models import (
    Contact,
    Message,
    Subscription,
    Workspace,
    WorkspaceMember,
)


class Suspended(Exception):
    pass


def require_platform_admin(db, user_id) -> None:
    from app.models import User

    user = db.get(User, user_id)
    if user is None or not user.is_platform_admin:
        raise PermissionError("Platform admin only")


def list_workspaces(db) -> list[dict]:
    rows = db.execute(select(Workspace)).scalars().all()
    out = []
    for ws in rows:
        members = db.execute(
            select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ws.id
            )
        ).scalar_one()
        messages = db.execute(
            select(func.count()).select_from(Message).where(Message.workspace_id == ws.id)
        ).scalar_one()
        sub = db.execute(
            select(Subscription).where(Subscription.workspace_id == ws.id)
        ).scalar_one_or_none()
        out.append({
            "name": str(ws.id), "workspace_name": ws.name,
            "suspended": bool((ws.settings or {}).get("suspended")),
            "members": members, "messages": messages,
            "status": sub.status if sub else "none",
            "plan": sub.plan if sub else None,
        })
    return out


def platform_stats(db) -> dict:
    workspaces = db.execute(select(func.count()).select_from(Workspace)).scalar_one()
    users = db.execute(
        select(func.count(func.distinct(WorkspaceMember.user_id)))
    ).scalar_one()
    messages = db.execute(select(func.count()).select_from(Message)).scalar_one()
    contacts = db.execute(select(func.count()).select_from(Contact)).scalar_one()
    by_status: dict[str, int] = {}
    for status, count in db.execute(
        select(Subscription.status, func.count()).group_by(Subscription.status)
    ).all():
        by_status[status] = count
    return {
        "totals": {"workspaces": workspaces, "users": users,
                   "messages": messages, "contacts": contacts},
        "by_subscription_status": by_status,
    }


def suspend(db, workspace_id, suspended: bool, reason: str | None = None) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return
    settings = dict(ws.settings or {})
    settings["suspended"] = suspended
    if reason:
        settings["suspended_reason"] = reason
    ws.settings = settings


def assert_can_send(db, workspace_id) -> None:
    """Single outbound chokepoint guard — suspended workspace cannot dispatch."""
    ws = db.get(Workspace, workspace_id)
    if ws is not None and (ws.settings or {}).get("suspended"):
        raise Suspended("Workspace is suspended")
