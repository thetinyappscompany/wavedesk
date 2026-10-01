"""Platform superadmin (System-Manager equivalent = User.is_platform_admin).
Cross-workspace, NOT tenant-scoped. + assert_can_send enforcement.

Suspension source of truth is the Workspace.suspended COLUMN (it's what the R8
cutover ETL populates from Frappe); the legacy settings-JSON flag written by
earlier deploys is still honored on read so previously-suspended workspaces
stay suspended."""

from sqlalchemy import func, or_, select

from app.models import (
    Contact,
    Message,
    Subscription,
    User,
    WhatsAppNumber,
    Workspace,
    WorkspaceMember,
)


class Suspended(Exception):
    pass


def _is_suspended(ws: Workspace) -> bool:
    """Column first (ETL + new writes), legacy settings flag as fallback."""
    return bool(ws.suspended or (ws.settings or {}).get("suspended"))


def require_platform_admin(db, user_id) -> None:
    user = db.get(User, user_id)
    if user is None or not user.is_platform_admin:
        raise PermissionError("Platform admin only")


def list_workspaces(db, search: str | None = None) -> list[dict]:
    """Rows in the WdAdminWorkspace shape the SPA's admin table reads
    (owner_user / send_rate_clamp / messages_total / subscription_status /
    creation — NOT internal names)."""
    query = select(Workspace)
    if search:
        query = query.where(func.lower(Workspace.name).like(f"%{search.lower()}%"))
    rows = db.execute(query).scalars().all()
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
        owner = db.execute(
            select(User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == ws.id,
                   WorkspaceMember.role == "Owner")
            .limit(1)
        ).scalar_one_or_none()
        out.append({
            "name": str(ws.id),
            "workspace_name": ws.name,
            "plan": sub.plan if sub else None,
            "owner_user": owner,
            "suspended": _is_suspended(ws),
            "send_rate_clamp": int((ws.settings or {}).get("send_rate_clamp") or 0),
            "members": members,
            "messages_total": messages,
            "subscription_status": sub.status if sub else None,
            "creation": ws.created_at.isoformat() if ws.created_at else None,
        })
    return out


def list_users(db, search: str | None = None, limit: int = 200) -> list[dict]:
    """Every account on the platform with the workspaces it belongs to. One
    membership query for the whole page — never N+1 per user."""
    query = select(User)
    if search:
        needle = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(User.email).like(needle),
                func.lower(User.first_name).like(needle),
            )
        )
    users = db.execute(
        query.order_by(User.created_at.desc()).limit(limit)
    ).scalars().all()
    if not users:
        return []

    memberships: dict[str, list[dict]] = {}
    rows = db.execute(
        select(WorkspaceMember.user_id, WorkspaceMember.role, Workspace.name)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id.in_([u.id for u in users]))
    ).all()
    for user_id, role, ws_name in rows:
        memberships.setdefault(str(user_id), []).append(
            {"workspace_name": ws_name, "role": role}
        )
    return [
        {
            "name": str(u.id),
            "email": u.email,
            "full_name": u.first_name,
            "enabled": bool(u.enabled),
            "is_platform_admin": bool(u.is_platform_admin),
            "workspaces": memberships.get(str(u.id), []),
            "creation": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


def platform_stats(db) -> dict:
    workspaces = db.execute(select(func.count()).select_from(Workspace)).scalar_one()
    # every account, including self-serve signups that haven't created a
    # workspace yet — matches what the admin Users table lists
    users = db.execute(select(func.count()).select_from(User)).scalar_one()
    messages = db.execute(select(func.count()).select_from(Message)).scalar_one()
    contacts = db.execute(select(func.count()).select_from(Contact)).scalar_one()
    numbers = db.execute(select(func.count()).select_from(WhatsAppNumber)).scalar_one()
    by_status: dict[str, int] = {}
    for status, count in db.execute(
        select(Subscription.status, func.count()).group_by(Subscription.status)
    ).all():
        by_status[status] = count
    by_plan = [
        {"plan": plan, "count": count}
        for plan, count in db.execute(
            select(Workspace.plan, func.count()).group_by(Workspace.plan)
        ).all()
    ]
    # One SQL count — never stream every settings blob into Python. Checks the
    # column (ETL + new writes) OR the legacy settings flag.
    suspended = db.execute(
        select(func.count()).select_from(Workspace).where(
            or_(
                Workspace.suspended.is_(True),
                Workspace.settings["suspended"].as_boolean().is_(True),
            )
        )
    ).scalar_one()
    return {
        "totals": {"workspaces": workspaces, "users": users, "messages": messages,
                   "contacts": contacts, "numbers": numbers},
        "operational": {"suspended": suspended},
        "by_subscription_status": by_status,
        "trial_vs_paid": {
            "trial": by_status.get("trialing", 0),
            "paid": by_status.get("active", 0),
            "past_due": by_status.get("past_due", 0),
        },
        "by_plan": by_plan,
    }


def suspend(db, workspace_id, suspended: bool, reason: str | None = None) -> None:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return
    ws.suspended = suspended  # the column is the source of truth
    settings = dict(ws.settings or {})
    settings.pop("suspended", None)  # converge legacy flag onto the column
    if reason:
        settings["suspended_reason"] = reason
    ws.settings = settings


def assert_can_send(db, workspace_id) -> None:
    """Single outbound chokepoint guard — suspended workspace cannot dispatch,
    and an operator-set daily send clamp caps outbound volume."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return
    settings = ws.settings or {}
    if _is_suspended(ws):
        raise Suspended("Workspace is suspended")
    clamp = int(settings.get("send_rate_clamp") or 0)
    if clamp > 0:
        from datetime import UTC, datetime

        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = db.execute(
            select(func.count()).select_from(Message).where(
                Message.workspace_id == workspace_id,
                Message.direction == "out",
                Message.is_private.is_(False),  # notes never left the app
                Message.created_at >= start,
            )
        ).scalar_one()
        if sent_today >= clamp:
            raise Suspended(f"Daily send clamp reached ({clamp})")
