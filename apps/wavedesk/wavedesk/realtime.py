"""Workspace realtime events (Phase 1 feature 2: 'No refresh, ever').

Events fan out to each member's USER room (auto-joined on socket connect,
authenticated by Frappe's socketio via the session cookie) — inherently
workspace-scoped because membership is checked here, server-side.
A shared `workspace:{id}` socket room (tenancy.py helpers) replaces the
fan-out when we customize the realtime node server; the event contract
below stays the same either way.

Events (payloads are ids + safe metadata only — bodies come via the REST
API which enforces permissions):
  wd:message         {chat, message, direction}       new message stored
  wd:message_status  {chat, message, status}          outbound status change
"""

import frappe


def workspace_members(workspace: str) -> list[str]:
    member = frappe.qb.DocType("WD Workspace Member")
    rows = (
        frappe.qb.from_(member)
        .select(member.user)
        .where((member.parent == workspace) & (member.parenttype == "WD Workspace"))
    ).run(pluck=True)
    return list(dict.fromkeys(rows))


def emit_workspace_event(workspace: str, event: str, payload: dict) -> None:
    """Emit to every workspace member after the surrounding transaction commits
    (an event about an uncommitted row would race the client's refetch)."""
    for user in workspace_members(workspace):
        frappe.publish_realtime(
            event=event,
            message=payload,
            user=user,
            after_commit=True,
        )


def emit_message(workspace: str, chat: str, message: str, direction: str) -> None:
    emit_workspace_event(
        workspace, "wd:message", {"chat": chat, "message": message, "direction": direction}
    )


def emit_message_status(workspace: str, chat: str, message: str, status: str) -> None:
    emit_workspace_event(
        workspace, "wd:message_status", {"chat": chat, "message": message, "status": status}
    )
