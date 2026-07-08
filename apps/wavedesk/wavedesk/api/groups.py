"""Groups API (Phase 2 feature 1) — powers the /groups registry page.

Read-only in this epic (bulk actions land with P2.3). Workspace from session;
queries additionally protected by the tenancy permission layer."""

import frappe
from frappe.query_builder import Order
from frappe.query_builder.functions import Count
from frappe.utils import now_datetime

from wavedesk.tenancy import get_active_workspace

PAGE_SIZE_MAX = 100


@frappe.whitelist()
def list_groups(search: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """Registry rows newest-activity first, with per-group message stats.

    Returns {groups: [...], total: int}. msgs_today counts messages on the
    group's chat since local midnight (guide column spec)."""
    workspace = get_active_workspace()
    limit = min(int(limit), PAGE_SIZE_MAX)
    offset = max(int(offset), 0)

    group = frappe.qb.DocType("WD Group")
    chat = frappe.qb.DocType("WD Chat")
    number = frappe.qb.DocType("WD WhatsApp Number")

    query = (
        frappe.qb.from_(group)
        .left_join(chat)
        .on(chat.group == group.name)
        .left_join(number)
        .on(group.number == number.name)
        .where(group.workspace == workspace)
    )
    if search:
        needle = f"%{search}%"
        query = query.where(group.subject.like(needle) | group.wa_group_id.like(needle))

    total = query.select(Count(group.name).as_("n")).run(as_dict=True)[0]["n"]

    rows = (
        query.select(
            group.name,
            group.wa_group_id,
            group.subject,
            group.description,
            group.member_count,
            group.invite_link,
            group.owned_by_us,
            group.number,
            number.display_name.as_("number_name"),
            chat.name.as_("chat"),
            chat.last_message_at,
            chat.unread_count,
        )
        .orderby(chat.last_message_at, order=Order.desc)
        .orderby(group.creation, order=Order.desc)
        .limit(limit)
        .offset(offset)
    ).run(as_dict=True)

    msgs_today = _messages_today({row["chat"] for row in rows if row["chat"]})
    for row in rows:
        row["last_message_at"] = str(row["last_message_at"]) if row["last_message_at"] else None
        row["owned_by_us"] = bool(row["owned_by_us"])
        row["unread_count"] = row["unread_count"] or 0
        row["msgs_today"] = msgs_today.get(row["chat"], 0)

    return {"groups": rows, "total": total}


def _messages_today(chat_names: set[str]) -> dict[str, int]:
    """{chat: count} of messages since local midnight — one grouped query."""
    if not chat_names:
        return {}
    day_start = now_datetime().replace(hour=0, minute=0, second=0, microsecond=0)
    message = frappe.qb.DocType("WD Message")
    rows = (
        frappe.qb.from_(message)
        .select(message.chat, Count(message.name).as_("n"))
        .where((message.chat.isin(list(chat_names))) & (message.creation >= day_start))
        .groupby(message.chat)
    ).run(as_dict=True)
    return {row["chat"]: row["n"] for row in rows}
