# Copyright (c) 2026, WaveDesk
# License: proprietary
"""Active-session management (master doc §Phase 5 feature 6, security).

Self-service listing + revocation of the caller's own Frappe login sessions
(the `tabSessions` store). Revoking deletes the session row, invalidating that
device immediately. sids are masked in listings — only the tail is shown."""

import frappe


def _current_sid() -> str | None:
    return getattr(frappe.local, "session", None) and frappe.session.sid


def list_sessions(user: str) -> list[dict]:
    rows = frappe.db.sql(
        """select sid, ipaddress, lastupdate, status from `tabSessions`
           where user = %s order by lastupdate desc""",
        (user,), as_dict=True,
    )
    current = _current_sid()
    out = []
    for r in rows:
        sid = r.get("sid") or ""
        out.append({
            "sid_tail": sid[-6:] if sid else "",
            "ip": r.get("ipaddress"),
            "last_active": str(r.get("lastupdate")) if r.get("lastupdate") else None,
            "status": r.get("status"),
            "current": bool(current and sid == current),
        })
    return out


def revoke_session(user: str, sid_tail: str) -> dict:
    """Revoke one of the caller's sessions by its (masked) sid tail."""
    sids = frappe.db.sql_list(
        "select sid from `tabSessions` where user = %s", (user,)
    )
    target = next((s for s in sids if s and s[-6:] == sid_tail), None)
    if not target:
        frappe.throw("Unknown session", frappe.DoesNotExistError)
    frappe.db.sql("delete from `tabSessions` where sid = %s and user = %s", (target, user))
    frappe.cache().hdel("session", target)
    frappe.db.commit()
    return {"revoked": sid_tail}


def revoke_other_sessions(user: str) -> dict:
    """Sign out every session except the caller's current one."""
    current = _current_sid()
    rows = frappe.db.sql_list("select sid from `tabSessions` where user = %s", (user,))
    revoked = 0
    for sid in rows:
        if sid and sid != current:
            frappe.db.sql("delete from `tabSessions` where sid = %s", (sid,))
            frappe.cache().hdel("session", sid)
            revoked += 1
    frappe.db.commit()
    return {"revoked": revoked}
