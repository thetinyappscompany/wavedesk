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


def platform_stats(db) -> dict:
    workspaces = db.execute(select(func.count()).select_from(Workspace)).scalar_one()
    users = db.execute(
        select(func.count(func.distinct(WorkspaceMember.user_id)))
    ).scalar_one()
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
                Message.created_at >= start,
            )
        ).scalar_one()
        if sent_today >= clamp:
            raise Suspended(f"Daily send clamp reached ({clamp})")
